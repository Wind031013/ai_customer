CREATE database 
-- 商品主表
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    category ENUM('top','pants') NOT NULL,
    description TEXT,
    price DECIMAL(10, 2) NOT NULL,
    image_url VARCHAR(500)
);
-- 商品属性表
CREATE TABLE product_attributes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    attribute_key VARCHAR(255) NOT NULL,
    attribute_value VARCHAR(255) NOT NULL,
    attribute_type ENUM('text','number','enum'),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);
-- 商品尺码表
CREATE TABLE product_sizes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    category ENUM('top', 'pants') NOT NULL,
    size_code VARCHAR(255) NOT NULL,
    height_range VARCHAR(255),
    weight_range VARCHAR(255),
    length DECIMAL(5,1),
    sleeve_length DECIMAL(5,1),
    bust DECIMAL(5,1),
    waist DECIMAL(5,1),
    hip DECIMAL(5,1),
    bottom_hem DECIMAL(5,1),
    stock INT NOT NULL,
    UNIQUE KEY unique_product_size (product_id, size_code)
);
-- 购买记录表
CREATE TABLE product_purchases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    user_id INT NOT NULL,
    purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    height DECIMAL(5,1),
    weight DECIMAL(5,1),
    gender ENUM('male', 'female'),
    age INT,
    size_code VARCHAR(255) NOT NULL,
    return_item BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (product_id) REFERENCES products(id),
    INDEX idx_product_sales (product_id, purchase_date)
);

