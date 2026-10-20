"""Run offline servo/cylinder analysis on the checked-in CSV export.

In VS Code, select the project's Python interpreter and choose Run Python File.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.analysis_agent import write_analysis


def main() -> None:
    input_csv = (
        PROJECT_ROOT
        / "data"
        / "input"
        / "MECN_MOE6_RUNTIMEPARAMMONITOR_WEBSCADA_JSON_PROCESSED_V02_20261016.csv"
    )
    parameter_dictionary = PROJECT_ROOT / "data" / "input" / "param_name_and_type.xlsx"
    output_dir = PROJECT_ROOT / "data" / "output" / "offline_analysis"

    result = write_analysis(input_csv, output_dir, parameter_dictionary)
    print(f"Analysis finished. Asset groups: {len(result.asset_summary)}")
    print(f"Records flagged for review: {len(result.anomaly_events)}")
    print(f"Report: {output_dir / 'analysis_report.md'}")


if __name__ == "__main__":
    main()
