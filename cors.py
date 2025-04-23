import json
import os
from fastapi import Request, Response, Cookie
from fastapi.responses import RedirectResponse
from request_helper import Requester
from typing import Annotated


async def cors(request: Request, origins, method="GET") -> Response:
    current_domain = request.headers.get("origin")
    if current_domain is None:
        current_domain = origins
    if current_domain not in origins.replace(", ", ",").split(",") and origins != "*":
        return Response()
    if not request.query_params.get('url'):
        return Response()
    file_type = request.query_params.get('type')
    requested = Requester(str(request.url))
    main_url = requested.host + requested.path + "?url="
    url = requested.query_params.get("url")
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
    headers['Access-Control-Allow-Origin'] = current_domain

    del_keys = [
        'Vary',
        'Content-Encoding',
        'Transfer-Encoding',
        'Content-Length',
    ]
    for key in del_keys:
        headers.pop(key, None)

    if (file_type == "m3u8" or ".m3u8" in url) and code != 404:
        content = content.decode("utf-8")
        new_content = ""
        base_url = requested.url.rsplit("/", 1)[0]
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                new_content += line + "\n"
                continue
            if stripped.startswith("http"):
                segment_url = stripped
            elif stripped.startswith("/"):
                segment_url = requested.scheme + "://" + requested.netloc + stripped
            else:
                segment_url = base_url + "/" + stripped

            # Force segment to go through the proxy (over HTTPS)
            proxied_segment = f"{main_url}{requested.safe_sub(segment_url)}&type=ts"
            new_content += proxied_segment + "\n"
        content = new_content

    if "location" in headers:
        if headers["location"].startswith("/"):
            headers["location"] = requested.host + headers["location"]
        headers["location"] = main_url + headers["location"]

    resp = Response(content, code, headers=headers)
    resp.set_cookie("_last_requested", requested.host, max_age=3600, httponly=True)
    return resp


def add_cors(app, origins, setup_with_no_url_param=False):
    cors_path = os.getenv('cors_url', '/cors')

    @app.get(cors_path)
    async def cors_caller(request: Request) -> Response:
        return await cors(request, origins=origins)

    @app.post(cors_path)
    async def cors_caller_post(request: Request) -> Response:
        return await cors(request, origins=origins, method="POST")

    if setup_with_no_url_param:
        @app.get("/{mistaken_relative:path}")
        async def cors_caller_for_relative(request: Request, mistaken_relative: str, _last_requested: Annotated[str, Cookie(...)]) -> RedirectResponse:
            x = Requester(str(request.url))
            x = x.query_string(x.query_params)
            resp = RedirectResponse(f"/cors?url={_last_requested}/{mistaken_relative}{'&' + x if x else ''}")
            return resp

        @app.post("/{mistaken_relative:path}")
        async def cors_caller_for_relative(request: Request, mistaken_relative: str,
                                           _last_requested: Annotated[str, Cookie(...)]) -> RedirectResponse:
            x = Requester(str(request.url))
            x = x.query_string(x.query_params)
            resp = RedirectResponse(f"/cors?url={_last_requested}/{mistaken_relative}{'&' + x if x else ''}")
            return resp
