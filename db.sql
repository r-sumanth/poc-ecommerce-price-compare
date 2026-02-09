CREATE DATABASE ecommerce_db;

CREATE TABLE price_matrix (
    id SERIAL PRIMARY KEY,
    product_name TEXT NOT NULL,
    price_amazon FLOAT,
    price_flipkart FLOAT,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product_name)
);