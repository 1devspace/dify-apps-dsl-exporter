import asyncio
import glob
import os
import sys

import httpx

import dify_api

DSL_FOLDER_PATH = os.getenv("DSL_FOLDER_PATH", "./dsl")


def get_dsl_files() -> list[str]:
    """
    Retrieve all .yml files from the DSL folder.

    :return: List of file paths to .yml files
    """
    yml_files = glob.glob(f"{DSL_FOLDER_PATH}/*.yml")
    if not yml_files:
        print(f"No YML files found in {DSL_FOLDER_PATH}")
        return []
    return yml_files


async def upload_yml_files(access_token: str | None, yml_files: list[str], client: httpx.AsyncClient):
    """
    Upload multiple YML files to the Dify API concurrently.

    :param access_token: Access token for authentication
    :param yml_files: List of paths to YML files to be uploaded
    :param client: An instance of httpx.AsyncClient
    """
    tasks = [
        asyncio.create_task(upload_yml_file(access_token, file_path, client))
        for file_path in yml_files
    ]
    await asyncio.gather(*tasks)


async def upload_yml_file(access_token: str | None, file_path: str, client: httpx.AsyncClient):
    """
    Upload a single YML file to the Dify API.

    :param access_token: Access token for authentication
    :param file_path: Path to the YML file
    :param client: An instance of httpx.AsyncClient
    """
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as file:
        yaml_content = file.read()

    if not yaml_content:
        print(f"❌ Skipping empty file: {file_path}")
        return

    response = await dify_api.import_app(access_token, yaml_content, client)
    app_name = os.path.basename(file_path)
    
    # Check for successful import (completed or completed-with-warnings)
    status = response.get("status", "")
    if status in ["completed", "completed-with-warnings"]:
        app_id = response.get("app_id") or response.get("data", {}).get("app_id")
        if status == "completed-with-warnings":
            print(f"✅ Imported with warnings: {app_name} -> App ID: {app_id}")
            if response.get("error"):
                print(f"   Warning: {response.get('error')}")
        else:
            print(f"✅ Imported: {app_name} -> App ID: {app_id}")
    elif response.get("result") == "success":
        # Response might have result field
        app_id = response.get("app_id") or response.get("data", {}).get("app_id")
        print(f"✅ Imported: {app_name} -> App ID: {app_id}")
    else:
        # Print full response for debugging
        error_msg = response.get("error") or response.get("message") or "Unknown error"
        print(f"❌ Failed to import: {app_name}")
        print(f"   Status: {status}")
        if error_msg and error_msg != "":
            print(f"   Error: {error_msg}")
        else:
            print(f"   Full response: {response}")


async def main():
    # Check if a specific file was provided as command line argument
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return
        
        # Use a single client instance to maintain cookies
        async with httpx.AsyncClient() as client:
            access_token = await dify_api.login_and_get_token(client)
            await upload_yml_file(access_token, file_path, client)
    else:
        # Import all files from dsl folder
        async with httpx.AsyncClient() as client:
            access_token = await dify_api.login_and_get_token(client)
            
            yml_files = get_dsl_files()
            if not yml_files:
                print("No YML files found to upload.")
                return
            
            await upload_yml_files(access_token, yml_files, client)


if __name__ == "__main__":
    asyncio.run(main())
