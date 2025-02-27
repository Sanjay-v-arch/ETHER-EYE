-- Transactions Table
CREATE TABLE transactions (
    tx_id TEXT PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address TEXT DEFAULT NULL  -- Can be updated later
);

-- Wallets Table
CREATE TABLE wallets (
    address TEXT PRIMARY KEY,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Transaction Inputs (For multi-input transactions)
CREATE TABLE transaction_inputs (
    id SERIAL PRIMARY KEY,
    tx_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    amount REAL CHECK (amount > 0),
    FOREIGN KEY (tx_id) REFERENCES transactions (tx_id) ON DELETE CASCADE,
    FOREIGN KEY (wallet_address) REFERENCES wallets (address) ON DELETE CASCADE
);

-- Transaction Outputs (For multi-output transactions)
CREATE TABLE transaction_outputs (
    id SERIAL PRIMARY KEY,
    tx_id TEXT NOT NULL,
    wallet_address TEXT NOT NULL,
    amount REAL CHECK (amount > 0),
    FOREIGN KEY (tx_id) REFERENCES transactions (tx_id) ON DELETE CASCADE,
    FOREIGN KEY (wallet_address) REFERENCES wallets (address) ON DELETE CASCADE
);

-- Entity Profiles (For tracking wallets involved in illicit activities)
CREATE TABLE entity_profiles (
    address TEXT PRIMARY KEY,
    risk_level TEXT CHECK (risk_level IN ('low', 'medium', 'high', 'unknown')),
    flagged BOOLEAN DEFAULT FALSE,
    notes TEXT,
    FOREIGN KEY (address) REFERENCES wallets (address) ON DELETE CASCADE
);

-- Investigation Cases (For law enforcement tracking)
CREATE TABLE investigation_cases (
    case_id SERIAL PRIMARY KEY,
    case_name TEXT UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Linking Transactions to Investigations
CREATE TABLE case_transactions (
    case_id INT NOT NULL,
    tx_id TEXT NOT NULL,
    FOREIGN KEY (case_id) REFERENCES investigation_cases (case_id) ON DELETE CASCADE,
    FOREIGN KEY (tx_id) REFERENCES transactions (tx_id) ON DELETE CASCADE
);

-- Indexes for performance optimization
CREATE INDEX idx_tx_id ON transactions (tx_id);
CREATE INDEX idx_wallet_address ON wallets (address);
CREATE INDEX idx_case_name ON investigation_cases (case_name);
