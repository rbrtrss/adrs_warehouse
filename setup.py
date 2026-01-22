from setuptools import setup, find_packages

setup(
    name="adrs-warehouse",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "pandas>=2.0.0",
        "yfinance>=0.2.0",
        "duckdb>=0.9.0",
    ],
    python_requires=">=3.9",
)