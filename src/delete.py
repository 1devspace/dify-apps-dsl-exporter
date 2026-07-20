import asyncio
import os
import sys

import httpx

import dify_api


async def delete_one(access_token: str | None, app_id: str, client: httpx.AsyncClient):
    """
    Delete a single app by its ID and verify it was removed.

    :param access_token: Access token for authentication
    :param app_id: ID of the app to delete
    :param client: HTTP client for making requests
    """
    await dify_api.delete_app(access_token, {"id": app_id, "name": app_id}, client)

    apps, _ = await dify_api.get_app_list(access_token, client)
    if any(app["id"] == app_id for app in apps):
        print(f"⚠️  App {app_id} still present after delete request.")
    else:
        print(f"✅ Confirmed deleted: {app_id}")


async def delete_apps(access_token: str | None, apps: list, client: httpx.AsyncClient):
    """
    Delete all apps concurrently using their IDs.

    :param access_token: Access token for authentication
    :param apps: List of apps with 'id' and 'name' fields
    :param client: HTTP client for making requests
    """
    tasks = [asyncio.create_task(dify_api.delete_app(access_token, app, client)) for app in apps]
    await asyncio.gather(*tasks)


def make_unique_app_names(apps: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Ensure all app names are unique by appending ID prefix to duplicates.

    :param apps: List of app dictionaries with 'id' and 'name'
    :return: Tuple of (list with unique app names, list of renamed name mappings)
    """
    unique_apps = []
    same_app_names = []
    seen_names = set()

    for app in apps:
        name = app["name"]
        if name in seen_names:
            modified_name = f"【same】{name}-{app['id'].split('-')[0]}"
            unique_apps.append({"id": app["id"], "name": modified_name})
            same_app_names.append(f"{name} -> {modified_name}")
        else:
            unique_apps.append(app)
            seen_names.add(name)

    return unique_apps, same_app_names


async def delete_single(app_id: str):
    """
    Delete a single app by ID. Does not require bulk confirmation.

    :param app_id: ID of the app to delete
    """
    async with httpx.AsyncClient() as client:
        access_token = await dify_api.login_and_get_token(client)
        await delete_one(access_token, app_id, client)


async def delete_all():
    """
    Delete all apps. Requires CONFIRM_DELETE_ALL=DELETE_ALL_WORKFLOWS.

    Steps:
    1. Authenticate and get an access token
    2. Fetch all apps
    3. Resolve name conflicts (for logging clarity)
    4. Delete each app concurrently
    """
    confirmation = os.getenv("CONFIRM_DELETE_ALL", "")
    if confirmation != "DELETE_ALL_WORKFLOWS":
        print("❌ Refusing to delete all workflows without confirmation.")
        print("   Set CONFIRM_DELETE_ALL=DELETE_ALL_WORKFLOWS in your environment to continue,")
        print("   or pass an app ID to delete a single workflow: python src/delete.py <app_id>")
        return

    async with httpx.AsyncClient() as client:
        # 1. Get access token or keep cookie-based auth in this client
        access_token = await dify_api.login_and_get_token(client)

        # 2. Get the list of apps
        apps, app_num = await dify_api.get_app_list(access_token, client)

        # 3. Check delete feasibility
        if not apps:
            print("❌ No apps found.")
            return
        if len(apps) != app_num:
            print("❌ Mismatch in the number of apps.")
            return

        # 4. Check unique app name
        unique_apps, same_app_names = make_unique_app_names(apps)
        print(f"Same name app count: {len(same_app_names)}, renamed list: {same_app_names}")

        # 5. Delete all apps concurrently
        print("Deleting apps...")
        await delete_apps(access_token, unique_apps, client)


async def main():
    """
    Delete a single app when an app ID is passed as an argument,
    otherwise delete all apps (gated behind CONFIRM_DELETE_ALL).
    """
    if len(sys.argv) > 1:
        await delete_single(sys.argv[1])
    else:
        await delete_all()


if __name__ == "__main__":
    asyncio.run(main())
