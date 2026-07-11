# Tableau Public scraper

This project contains a production-oriented Python starter for extracting data from the Tableau Public workbook at the supplied URL.

## Requirements

- Python 3.12
- Windows environment

## Setup

1. Create a virtual environment:
   `python -m venv .venv`
2. Activate it:
   `.venv\Scripts\Activate.ps1`
3. Install dependencies:
   `pip install -r requirements.txt`
4. Run the scraper:
   `python main.py`

## Outputs

- `output/fiber_data.csv`
- `output/fiber_data.xlsx`
- `output/sample.csv`

The implementation attempts to use `tableauscraper` first and falls back to website/API inspection if needed.
