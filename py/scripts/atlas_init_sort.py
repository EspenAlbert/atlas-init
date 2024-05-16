import sys
from pathlib import Path

from model_lib import dump, parse_model

from atlas_init.settings.config import AtlasInitConfig


def main():
    scripts_path = Path(__file__).parent
    repo_path = scripts_path.parent.parent
    config_path = repo_path / "atlas_init.yaml"
    old = config_path.read_text()
    config = parse_model(config_path, t=AtlasInitConfig)
    config.test_suites = sorted(config.test_suites)
    new = dump(config, "yaml")
    if old == new:
        print("config is sorted ✅")
        return
    print(f"config is not sorted ❌ {config_path.name}")
    config_path.write_text(new)
    sys.exit(1)


if __name__ == "__main__":
    main()
