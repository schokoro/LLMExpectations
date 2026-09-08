import marimo

__generated_with = "0.24.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    from datetime import datetime
    from typing import List
    import re
    from pathlib import Path

    return List, Path, re


@app.cell
def _(List, Path, re):
    def filter_dates(path: Path, threshold_date="2019-11-01") -> List[str]:
        def date_for_compare(date: str) -> int:    
            date = [int(d) for d in date.split('-')]
            return 10000 * date[0] + 100 * date[1] + date[2]
        threshold = date_for_compare(threshold_date)
        raw_dates = sorted(set(re.findall(r'\d{4}-\d{2}-\d{2}', Path(path).read_text(encoding='utf-8'))))
        filtered_dates = [date for date in raw_dates if date_for_compare(date) > threshold]
        return filtered_dates


    return (filter_dates,)


@app.cell
def _(filter_dates):
    filtered_dates_1 = [f"{d}\n" for d in filter_dates("data/run_dates/dates_for_news_aggregation_1.txt")]
    with open("data/run_dates/run_dates_1.txt", "wt") as fp1:
        fp1.writelines(filtered_dates_1)
    return


@app.cell
def _(filter_dates):
    filtered_dates_2 = [f"{d}\n" for d in filter_dates("data/run_dates/dates_for_news_aggregation_2.txt")]
    with open("data/run_dates/run_dates_2.txt", "wt") as fp2:
        fp2.writelines(filtered_dates_2)
    return


@app.cell
def _():
    # filtered_dates_1
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
