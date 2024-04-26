def replace_client(text: str, old_version: str, new_client_field: str = "client.AtlasSDK") -> str:
    return text.replace(f"client.Atlas{old_version.removeprefix('v')}", new_client_field)
