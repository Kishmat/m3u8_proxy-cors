import json
import os
from fastapi import Request, Response, Cookie
from fastapi.responses import RedirectResponse
from request_helper import Requester
from typing import Annotated
from urllib.parse import quote, urlparse


async def cors(request: Request, origins, method="GET") -> Response:
    allowed_origins = origins.replace(", ", ",").split(",")
    current_origin = request.headers.get("origin")

    # Allow localhost testing
    if current_origin is None:
        client_host = request.client.host
        if client_host in ("127.0.0.1", "localhost"):
            current_origin = "http://localhost"
        else:
            return Response(status_code=403)

    if origins != "*" and current_origin not in allowed_origins:
        return Response(status_code=403)

    if not request.query_params.get('url'):
        return Response("Missing 'url' parameter", status_code=400)

    file_type = request.query_params.get('type')
    original_url = request.query_params.get("url")
    requested = Requester(original_url)
    base_url = requested.host + requested.path.rsplit("/", 1)[0]

    # For building proxy paths
    main_url = str(request.url).split("?")[0] + "?url="
    additional_query = requested.query_string(requested.remaining_params)

    headers = request.headers.mutablecopy()
    headers["Accept-Encoding"] = ""
    headers.update(json.loads(request.query_params.get("headers", "{}").replace("'", '"')))

    content, resp_headers, code, _ = requested.get(
        data=None,
        headers=headers,
        cookies=request.cookies,
        method=request.query_params.get("method", method),
        json_data=json.loads(request.query_params.get("json", "{}")),
        additional_params=json.loads(request.query_params.get("params", "{}"))
    )

    resp_headers['Access-Control-Allow-Origin'] = current_origin

    # Strip unwanted headers
    for key in ["Vary", "Content-Encoding", "Transfer-Encoding", "Content-Length"]:
        resp_headers.pop(key, None)

    # If m3u8, rewrite its contents
    if (file_type == "m3u8" or ".m3u8" in original_url) and code != 404:
        content = content.decode("utf-8")
        new_content = ""

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                new_content += line + "\n"
                continue

            # Rewriting URLs to go through proxy
            if stripped.startswith("http"):
                proxied = main_url + quote(stripped, safe="")
            elif stripped.startswith("/"):
                full = f"https://{requested.netloc}{stripped}"
                proxied = main_url + quote(full, safe="")
            else:
                # Relative paths
                full = f"https://{requested.netloc}/{base_url}/{stripped}".replace("//", "/").replace(":/", "://")
                proxied = main_url + quote(full, safe="")

            if additional_query:
                proxied += "&" + additional_query

            new_content += proxied + "\n"

        content = new_content.encode("utf-8")

    return Response(content, status_code=code, headers=resp_headers)


def add_cors(app, origins, setup_with_no_url_param=False):
    cors_path = os.getenv('cors_url', '/cors')

    @app.get(cors_path)
    async def cors_get(request: Request) -> Response:
        return await cors(request, origins=origins)

    @app.post(cors_path)
    async def cors_post(request: Request) -> Response:
        return await cors(request, origins=origins, method="POST")

    if setup_with_no_url_param:
        @app.get("/{mistaken_relative:path}")
        async def redirect_get(request: Request, mistaken_relative: str, _last_requested: Annotated[str, Cookie(...)]) -> RedirectResponse:
            x = Requester(str(request.url))
            qs = x.query_string(x.query_params)
            return RedirectResponse(f"/cors?url={_last_requested}/{mistaken_relative}{'&' + qs if qs else ''}")

        @app.post("/{mistaken_relative:path}")
        async def redirect_post(request: Request, mistaken_relative: str, _last_requested: Annotated[str, Cookie(...)]) -> RedirectResponse:
            x = Requester(str(request.url))
            qs = x.query_string(x.query_params)
            return RedirectResponse(f"/cors?url={_last_requested}/{mistaken_relative}{'&' + qs if qs else ''}")
