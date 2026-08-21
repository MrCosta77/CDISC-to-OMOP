import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.etl.build_database import validate_published_database


def main():
    result = validate_published_database()
    print(
        f"✅ OMOP CDM {result['cdm_version']} ({result['source_release']}) "
        f"accepted: {result['schema_table_count']} official tables."
    )
    for table, count in result["row_counts"].items():
        print(f" - {table}: {count} rows")


if __name__ == "__main__":
    main()
