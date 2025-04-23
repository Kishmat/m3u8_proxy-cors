import json
import os
from fastapi import Request, Response, Cookie
from fastapi.responses import RedirectResponse
from request_helper import Requester
from typing import Annotated
from urllib.parse import urlparse


async def cors(request: Request, origins="*", method="GET") -> Response:
    if not request.query_params.get('url'):
        return Response(status_code=400)

    file_type = request.query_params.get('type')
    requested = Requester(str(request.url))
    main_url = requested.host + requested.path + "?url="
    url = request.query_params.get("url")

    if requested.remaining_params:
        url += "?" + requested.query_string(requested.remaining_params)

    requested = Requester(url)
    hdrs = request.headers.mutablecopy()
    hdrs["Accept-Encoding"] = ""
    hdrs.update(json.loads(request.query_params.get("headers", "{}").replace("'", '"')))

    content, headers, code, cookies = requested.get(
        data=None,
        headers=hdrs,
        cookies=request.cookies,
        method=request.query_params.get("method", method),
        json_data=json.loads(request.query_params.get("json", "{}")),
        additional_params=json.loads(request.query_params.get("params", "{}"))
    )

    headers['Access-Control-Allow-Origin'] = "*"
    for key in ['Vary', 'Content-Encoding', 'Transfer-Encoding', 'Content-Length']:
        headers.pop(key, None)

    # ✅ Force HTTPS in m3u8 rewriting
    if (file_type == "m3u8" or ".m3u8" in url) and code != 404:
        content = content.decode("utf-8")
        base_url = requested.url.rsplit("/", 1)[0]
        new_content = ""

        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_content += line + "\n"
                continue

            if stripped.startswith("http"):
                parsed = urlparse(stripped)
                # Force https even if original is http
                segment_url = "https://" + parsed.netloc + parsed.path
            elif stripped.startswith("/"):
                segment_url = "https://" + requested.netloc + stripped
            else:
                segment_url = f"https://{requested.netloc}{requested.path.rsplit('/', 1)[0]}/{stripped}"

            proxied_url = main_url + requested.safe_sub(segment_url)
            new_content += proxied_url + "\n"

        content = new_content

    if "location" in headers:
        loc = headers["location"]
        if loc.startswith("/"):
            loc = requested.host + loc
        headers["location"] = main_url + loc

    resp = Response(content, code, headers=headers)
    resp.set_cookie("_last_requested", requested.host, max_age=3600, httponly=True)
    return resp


def add_cors(app, origins="*", setup_with_no_url_param=False):
    cors_path = os.getenv('cors_url', '/cors')

    @app.get(cors_path)
    async def cors_get(request: Request) -> Response:
        return await cors(request)

    @app.post(cors_path)
    async def cors_post(request: Request) -> Response:
        return await cors(request, method="POST")

    if setup_with_no_url_param:
        @app.get("/{mistaken_relative:path}")
        async def fallback_get(request: Request, mistaken_relative: str, _last_requested: Annotated[str, Cookie(...)]) -> RedirectResponse:
            x = Requester(str(request.url))
            query = x.query_string(x.query_params)
            return RedirectResponse(f"/cors?url={_last_requested}/{mistaken_relative}" + (f"&{query}" if query else ""))

        @app.post("/{mistaken_relative:path}")
        async def fallback_post(request: Request, mistaken_relative: str, _last_requested: Annotated[str, Cookie(...)]) -> RedirectResponse:
            x = Requester(str(request.url))
            query = x.query_string(x.query_params)
            return RedirectResponse(f"/cors?url={_last_requested}/{mistaken_relative}" + (f"&{query}" if query else ""))
