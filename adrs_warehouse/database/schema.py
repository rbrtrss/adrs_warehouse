"""SQL DDL statements for the star schema."""

DIM_DATE_DDL = """
CREATE TABLE IF NOT EXISTS dim_date (
    date_id INTEGER PRIMARY KEY,
    date DATE NOT NULL,
    year INTEGER NOT NULL,
    quarter INTEGER NOT NULL,
    month INTEGER NOT NULL,
    month_name VARCHAR NOT NULL,
    day INTEGER NOT NULL,
    day_of_week INTEGER NOT NULL,
    day_name VARCHAR NOT NULL,
    week_of_year INTEGER NOT NULL,
    is_weekend BOOLEAN NOT NULL,
    is_month_start BOOLEAN NOT NULL,
    is_month_end BOOLEAN NOT NULL
);
"""

DIM_TICKER_DDL = """
CREATE TABLE IF NOT EXISTS dim_ticker (
    ticker_id INTEGER PRIMARY KEY,
    ticker_symbol VARCHAR NOT NULL UNIQUE,
    company_name VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    sector VARCHAR NOT NULL,
    country VARCHAR NOT NULL,
    first_trade_date DATE,
    last_trade_date DATE
);
"""

FACT_STOCK_PRICES_DDL = """
CREATE TABLE IF NOT EXISTS fact_stock_prices (
    date_id INTEGER NOT NULL,
    ticker_id INTEGER NOT NULL,
    open_price DOUBLE,
    high_price DOUBLE,
    low_price DOUBLE,
    close_price DOUBLE,
    adj_close_price DOUBLE,
    volume BIGINT,
    PRIMARY KEY (date_id, ticker_id),
    FOREIGN KEY (date_id) REFERENCES dim_date(date_id),
    FOREIGN KEY (ticker_id) REFERENCES dim_ticker(ticker_id)
);
"""

CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_fact_date ON fact_stock_prices(date_id);
CREATE INDEX IF NOT EXISTS idx_fact_ticker ON fact_stock_prices(ticker_id);
CREATE INDEX IF NOT EXISTS idx_dim_date_year_month ON dim_date(year, month);
CREATE INDEX IF NOT EXISTS idx_dim_ticker_symbol ON dim_ticker(ticker_symbol);
"""

ALL_DDL = [DIM_DATE_DDL, DIM_TICKER_DDL, FACT_STOCK_PRICES_DDL, CREATE_INDEXES]
