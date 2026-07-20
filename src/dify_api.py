import asyncio
import logging
import os

import httpx
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def _load_config() -> None:
    global DIFY_ORIGIN, BASE_URL, EMAIL, PASSWORD, INCLUDE_SECRET, AUTHOR_IGNORE_EMAILS
    DIFY_ORIGIN = os.getenv("DIFY_ORIGIN", "http://localhost").rstrip("/")
    BASE_URL = f"{DIFY_ORIGIN}/console/api"
    EMAIL = os.getenv("EMAIL")
    PASSWORD = os.getenv("PASSWORD")
    INCLUDE_SECRET = os.getenv("DIFY_INCLUDE_SECRET", "false").lower() in {"1", "true", "yes"}
    # Accounts to ignore when guessing a workflow's author from version/draft
    # history. The bulk importer shows up as creator/editor on every app, so it
    # is pure noise for attribution. Defaults to the importer/admin email.
    raw = os.getenv("AUTHOR_SUGGESTION_IGNORE_EMAILS", "")
    AUTHOR_IGNORE_EMAILS = {e.strip().lower() for e in raw.split(",") if e.strip()}


_load_config()
logger.info(f"Using Dify API at {BASE_URL} with email {EMAIL}")


def refresh() -> None:
    """Re-read Dify config from the environment (used by the Settings tab)."""
    _load_config()

MAX_CONCURRENT_TASKS = 3
semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

# Global variable to store CSRF token from login
_csrf_token: str | None = None


async def execute_api(
    client: httpx.AsyncClient,
    url: str,
    access_token: str | None = None,
    params: dict[str, str] | None = None,
    payload: dict | None = None,
    method_type: str = "POST",
    retries: int = 3,
) -> dict:
    """
    Execute an API request with retries and optional authorization.

    :param client: An instance of httpx.AsyncClient (cookies are automatically included)
    :param url: Target API endpoint URL
    :param access_token: Bearer token for authentication (optional, cookies used if None)
    :param params: Query parameters to include in the request (for GET)
    :param payload: Request payload to send (for POST)
    :param method_type: HTTP method (currently supports only 'POST')
    :param retries: Number of retry attempts on failure
    :return: Response body as a dictionary
    :raises Exception: If all retry attempts fail
    """
    headers = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    # Add CSRF token if available (some APIs require it)
    if _csrf_token:
        headers["X-CSRF-Token"] = _csrf_token
    async with semaphore:
        for attempt in range(retries):
            if method_type == "POST":
                response = await client.post(url, headers=headers, params=params, json=payload)
            elif method_type == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method_type == "DELETE":
                response = await client.delete(url, headers=headers)
            else:
                raise ValueError("Invalid method type")

            if response.status_code == 200:
                return response.json() if response.content else {}
            if method_type == "DELETE" and response.status_code == 204:
                return {}
            else:
                print(f"Attempt {attempt + 1} failed: {response.status_code} - {url}")
                await asyncio.sleep(0.5)

    raise Exception(f"API call failed after {retries} attempts: {url}")


async def login_and_get_token(client: httpx.AsyncClient) -> str | None:
    """
    Log in to the Dify API and retrieve an access token or set up cookie-based auth.

    :param client: An instance of httpx.AsyncClient (cookies will be stored in this client)
    :return: Access token string if available, None if using cookie-based auth
    :raises Exception: If login fails or API call fails
    """
    global _csrf_token
    payload = {"email": EMAIL, "password": PASSWORD}
    url = f"{BASE_URL}/login"
    
    # Make the login request directly to access headers and cookies
    async with semaphore:
        response = await client.post(url, json=payload)
        
        if response.status_code == 200:
            response_data = response.json() if response.content else {}
            
            if response_data.get("result") == "success":
                # Try to get token from response body first (not from cookies)
                access_token = None
                
                logger.debug(f"Login response data: {response_data}")
                
                if "data" in response_data and "access_token" in response_data["data"]:
                    access_token = response_data["data"]["access_token"]
                    logger.info("Found access_token in response.data.access_token")
                elif "access_token" in response_data:
                    access_token = response_data["access_token"]
                    logger.info("Found access_token in response.access_token")
                else:
                    # Check headers for token (not cookies - cookies are for session auth)
                    auth_header = response.headers.get("Authorization")
                    if auth_header and auth_header.startswith("Bearer "):
                        access_token = auth_header[7:]
                        logger.info("Found access_token in Authorization header")
                
                # If we have a token in the response body/header, use it
                if access_token:
                    print("Access token obtained successfully")
                    logger.info(f"Using Bearer token authentication")
                    return access_token
                elif response.cookies:
                    # Check if access_token is in cookies - extract it for Bearer auth
                    cookie_access_token = response.cookies.get("access_token")
                    if cookie_access_token:
                        # Extract the JWT token from the cookie and use it as Bearer token
                        print("Access token obtained from cookie - using Bearer token authentication")
                        logger.info(f"Using access_token from cookie as Bearer token")
                        logger.info(f"Cookies set: {list(response.cookies.keys())}")
                        # Store CSRF token if available
                        _csrf_token = response.cookies.get("csrf_token")
                        if _csrf_token:
                            logger.info("CSRF token stored for API requests")
                        return cookie_access_token
                    else:
                        # Cookie-based authentication - cookies are stored in the client
                        print("Login successful - using cookie-based authentication")
                        logger.info(f"Cookies set: {list(response.cookies.keys())}")
                        logger.info(f"Cookie values: {dict(response.cookies)}")
                        return None  # Return None to indicate cookie-based auth
                else:
                    logger.error(f"Token not found in response body or headers, and no cookies set")
                    logger.error(f"Response body: {response_data}")
                    logger.error(f"Response headers: {dict(response.headers)}")
                    logger.error(f"Response cookies: {dict(response.cookies)}")
                    raise Exception(f"Login response missing access_token and cookies. Response: {response_data}")
            else:
                logger.error(f"Login API error: {response_data.get('result')} - {url}")
                logger.error(f"Full response: {response_data}")
                raise Exception(f"Login failed. Response: {response_data}")
        else:
            logger.error(f"Login request failed with status {response.status_code}")
            raise Exception(f"Login failed with status {response.status_code}")


async def fetch_app_per_page(
    access_token: str | None, page: int, limit: int, client: httpx.AsyncClient
) -> dict:
    """
    Fetch a single page of app data from the Dify API.

    :param access_token: Access token for authentication
    :param page: Page number to fetch
    :param limit: Number of apps per page
    :param retries: Number of retry attempts on failure
    :param client: An instance of httpx.AsyncClient
    :return: Dictionary containing app data
    """
    return await execute_api(
        client,
        f"{BASE_URL}/apps",
        access_token=access_token,
        params={"page": page, "limit": limit},
        method_type="GET"
    )


async def get_app_list(access_token: str | None, client: httpx.AsyncClient) -> tuple[list, int]:
    """
    Retrieve all apps available to the authenticated user.

    :param access_token: Access token for authentication
    :param client: An instance of httpx.AsyncClient
    :return: Tuple of (list of app info dictionaries, total number of apps)
    """
    app_list = []
    page = 1
    limit = 30
    app_num = 0
    while True:
        content = await fetch_app_per_page(access_token, page, limit, client)

        if page == 1:
            app_num = content.get("total", 0)
            max_page_num = app_num // limit + (app_num % limit > 0)
            print(f"Total apps: {app_num}, Total pages: {max_page_num}")

        if app_num == 0:
            return [], 0

        if page > max_page_num:
            break

        app_per_page = [
            {"id": app.get("id"), "name": app.get("name")}
            for app in content.get("data", [])
        ]
        app_list.extend(app_per_page)
        page += 1

    return app_list, app_num


async def get_app_details(access_token: str | None, client: httpx.AsyncClient) -> list[dict]:
    """
    Retrieve all apps with the metadata needed for the workflow tracker.

    :param access_token: Access token for authentication
    :param client: An instance of httpx.AsyncClient
    :return: List of dicts with id, name, author, created_at, updated_at, tags
    """
    apps: list[dict] = []
    page = 1
    limit = 30
    total = 0
    max_page_num = 0
    while True:
        content = await fetch_app_per_page(access_token, page, limit, client)

        if page == 1:
            total = content.get("total", 0)
            max_page_num = total // limit + (total % limit > 0)

        if total == 0:
            return []

        for app in content.get("data", []):
            tags = app.get("tags") or []
            tag_names = ", ".join(t.get("name", "") for t in tags if t.get("name"))
            apps.append(
                {
                    "id": app.get("id"),
                    "name": app.get("name"),
                    "author": app.get("author_name") or "",
                    "created_at": app.get("created_at"),
                    "updated_at": app.get("updated_at"),
                    "tags": tag_names,
                }
            )

        if page >= max_page_num:
            break
        page += 1

    return apps


async def delete_app(access_token: str, app: dict, client: httpx.AsyncClient):
    """
    Delete a single app using its ID.

    :param access_token: Access token for authentication
    :param app: Dictionary with 'id' and 'name' keys
    :param client: HTTP client for making requests
    :return: None
    """
    url = f"{BASE_URL}/apps/{app['id']}"
    try:
        await execute_api(client, url, access_token=access_token, method_type="DELETE")
        print(f"🗑️  Deleted: {app['name']} (ID: {app['id']})")
    except Exception as e:
        print(f"❌ Failed to delete {app['name']} (ID: {app['id']}): {e}")


def _auth_headers(access_token: str | None) -> dict[str, str]:
    """Build auth + CSRF headers for a console API request."""
    headers: dict[str, str] = {}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if _csrf_token:
        headers["X-CSRF-Token"] = _csrf_token
    return headers


async def list_tags(
    access_token: str | None, client: httpx.AsyncClient, tag_type: str = "app"
) -> list[dict]:
    """List all tags of a given type (e.g. 'app'). Returns dicts with id, name, type."""
    resp = await client.get(
        f"{BASE_URL}/tags", params={"type": tag_type}, headers=_auth_headers(access_token)
    )
    resp.raise_for_status()
    return resp.json() if resp.content else []


async def create_tag(
    access_token: str | None, client: httpx.AsyncClient, name: str, tag_type: str = "app"
) -> dict:
    """Create a new tag and return it (dict with id, name, type)."""
    resp = await client.post(
        f"{BASE_URL}/tags",
        json={"name": name, "type": tag_type},
        headers=_auth_headers(access_token),
    )
    if resp.status_code not in (200, 201):
        raise Exception(f"Failed to create tag '{name}': {resp.status_code} - {resp.text[:200]}")
    return resp.json()


async def bind_tags(
    access_token: str | None,
    client: httpx.AsyncClient,
    tag_ids: list[str],
    target_id: str,
    tag_type: str = "app",
) -> None:
    """Bind one or more existing tags to a target (e.g. an app). Additive; never unbinds."""
    if not tag_ids:
        return
    resp = await client.post(
        f"{BASE_URL}/tag-bindings/create",
        json={"tag_ids": tag_ids, "target_id": target_id, "type": tag_type},
        headers=_auth_headers(access_token),
    )
    if resp.status_code not in (200, 201, 204):
        raise Exception(
            f"Failed to bind tags {tag_ids} to {target_id}: {resp.status_code} - {resp.text[:200]}"
        )


async def unbind_tag(
    access_token: str | None,
    client: httpx.AsyncClient,
    tag_id: str,
    target_id: str,
    tag_type: str = "app",
) -> None:
    """Remove a single tag binding from a target (e.g. an app)."""
    resp = await client.post(
        f"{BASE_URL}/tag-bindings/remove",
        json={"tag_id": tag_id, "target_id": target_id, "type": tag_type},
        headers=_auth_headers(access_token),
    )
    if resp.status_code not in (200, 201, 204):
        raise Exception(
            f"Failed to unbind tag {tag_id} from {target_id}: {resp.status_code} - {resp.text[:200]}"
        )


def _clean_actor(actor: dict | None) -> dict | None:
    """Return {name, email} for a Dify actor, unless it's an ignored account."""
    if not actor:
        return None
    email = (actor.get("email") or "").strip()
    name = (actor.get("name") or "").strip()
    if not name and not email:
        return None
    if email.lower() in AUTHOR_IGNORE_EMAILS:
        return None
    return {"name": name or email, "email": email}


async def suggest_author(
    access_token: str | None, app_id: str, client: httpx.AsyncClient
) -> dict | None:
    """Guess a workflow's real author from Dify history.

    Strategy (best signal first):
      1. Published version history (`/workflows`): whoever published the most
         recent version wins (excluding ignored accounts like the importer).
      2. Draft `updated_by`: the last person who edited the draft.
    Returns {name, email, source, candidates} or None when nothing is known.
    `candidates` lists every distinct contributor (newest first) for context.
    """
    headers = _auth_headers(access_token)

    # 1) Published versions — each carries its own publisher.
    try:
        resp = await client.get(
            f"{BASE_URL}/apps/{app_id}/workflows", params={"page": 1, "limit": 50}, headers=headers
        )
        items = resp.json().get("items", []) if resp.status_code == 200 and resp.content else []
    except (httpx.HTTPError, ValueError):
        items = []

    versions = sorted(items, key=lambda it: it.get("created_at") or 0, reverse=True)
    candidates: list[dict] = []
    seen: set[str] = set()
    for it in versions:
        actor = _clean_actor(it.get("created_by"))
        if actor and actor["name"] not in seen:
            seen.add(actor["name"])
            candidates.append(actor)
    if candidates:
        top = candidates[0]
        return {**top, "source": "published", "candidates": candidates}

    # 2) Fall back to the draft's last editor.
    try:
        resp = await client.get(f"{BASE_URL}/apps/{app_id}/workflows/draft", headers=headers)
        draft = resp.json() if resp.status_code == 200 and resp.content else {}
    except (httpx.HTTPError, ValueError):
        draft = {}
    actor = _clean_actor(draft.get("updated_by")) or _clean_actor(draft.get("created_by"))
    if actor:
        return {**actor, "source": "draft", "candidates": [actor]}

    return None


async def export_app(access_token: str | None, app_id: str, client: httpx.AsyncClient) -> bytes:
    """
    Export the app's DSL data as a bytes.

    :param access_token: Access token for authentication
    :param app_id: ID of the app to export
    :param client: An instance of httpx.AsyncClient
    :return: App DSL data as bytes
    :raises Exception: If the API call fails
    """
    include_secret = "true" if INCLUDE_SECRET else "false"
    url = f"{BASE_URL}/apps/{app_id}/export?include_secret={include_secret}"
    response = await execute_api(client, url, access_token, method_type="GET")
    
    # Handle different possible response structures
    if "data" in response:
        dsl_content = response["data"]
    elif isinstance(response, str):
        dsl_content = response
    else:
        logger.error(f"Unexpected export response structure: {response}")
        raise Exception(f"Export response missing data. Response: {response}")
    
    if isinstance(dsl_content, str):
        return dsl_content.encode("utf-8")
    return dsl_content


async def import_app(access_token: str | None, yaml_content: str, client: httpx.AsyncClient) -> dict:
    """
    Import an app using YAML content.
    :param access_token: Access token for authentication
    :param yaml_content: YAML content to import
    :param client: An instance of httpx.AsyncClient
    :return: Response from the API
    """
    url = f"{BASE_URL}/apps/imports"
    payload = {
        "mode": "yaml-content",
        "yaml_content": yaml_content
    }
    return await execute_api(client, url, access_token, payload=payload, method_type="POST")
