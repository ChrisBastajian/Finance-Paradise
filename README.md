# 📈 Finance Paradise Market Simulator

[![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Framework-Flask-lightgrey)](https://flask.palletsprojects.com/)
[![Repository](https://img.shields.io/badge/GitHub-Finance__Paradise-brightgreen)](https://github.com/ChrisBastajian/Finance-Paradise)

---

## 📌 Overview

Welcome to **Finance Paradise**, a high-performance web application that simulates a live, dynamic financial market.

Built with a custom Python order-matching engine and a Flask backend, this simulator:
- Generates real-time candlestick data  
- Maintains a live order book  
- Enables paper trading against AI-driven market participants  

---

## ✨ Key Features

- **Live Order Matching Engine**  
  Runs in a dedicated Python background daemon thread, continuously processing bids, asks, and trade volume without blocking the web server.

- **Dynamic AI Traders**  
  Includes multiple trader archetypes:
  - Trend Followers  
  - Mean-Reverting Traders  
  - Panic Traders  
  - Fundamental Traders  
  - Noise Traders  

- **Real-Time Sentiment Shifts**  
  A built-in **Market News system** dynamically alters trader behavior probabilities, simulating real-world volatility and shocks.

- **Interactive Web UI**  
  Dashboard includes:
  - Account Balance  
  - Realized PnL  
  - Open Positions  
  - Real-time candlestick charts  

- **Fault-Tolerant Simulation Loop**  
  Designed with safeguards for floating-point precision and edge cases to ensure continuous, stable execution.

---

## 📸 Dashboard Overview

> **Note:** Upload your screenshot (`image_f19e1c.jpg`) to the repository and ensure the path is correct.

![Finance Paradise Dashboard](image_f19e1c.jpg)

### The interface allows you to:
1. Select market sectors and timeframes  
2. Execute **BUY** and **SELL** orders  
3. Track your `$100,000` starting portfolio  
4. Inject custom market news events  

---

## 📂 Project Structure

```text
Finance-Paradise/
└── complete_implementation_final/
    ├── static/                # CSS, JavaScript, images
    ├── templates/             # Flask HTML templates
    │   ├── chart.html         # Trading dashboard
    │   ├── index.html         # Landing page
    │   └── search.html        # Asset search
    ├── app.py                 # Core backend (engine + routes)
    └── news.json              # Market news data source
---

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/ChrisBastajian/Finance-Paradise.git
cd Finance-Paradise/complete_implementation_final
```

---

### 2. Install Dependencies

Ensure you have **Python 3.8+** installed.

```bash
pip install Flask numpy
```

> Optional (recommended): create a virtual environment

```bash
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows
pip install Flask numpy
```

---

### 3. Run the Application

```bash
python app.py
```

- Starts Flask server  
- Launches simulation daemon thread automatically  

---

### 4. Access the Simulator

Open your browser:

```
http://127.0.0.1:5000
```

---

## 🛠️ Technical Details

### Backend
- Python  
- Flask  
- threading (simulation engine)  

### Frontend
- HTML5  
- CSS3  
- JavaScript  

### Core Engine
- Continuous Double Auction (CDA)  
- Price-time priority matching  
- In-memory order book  

### Probability System
- `random.choices()` for:
  - Trader selection  
  - Market regime shifts  
- Designed for long-run numerical stability  

---

## ⚙️ Core Concepts

### Continuous Double Auction (CDA)

- Orders match when:

```
highest_bid >= lowest_ask
```

- Execution price determined by matching logic  

---

### AI Trader System

- Trend → momentum following  
- Mean-Reverting → equilibrium seeking  
- Panic → volatility driven  
- Fundamental → reacts to news  
- Noise → stochastic behavior  

Behavior adapts based on:
- Market trend  
- Volatility  
- News events  

---

### Market Stability

Handles:
- Infinite trends  
- Negative prices  
- Floating-point drift  
- Liquidity collapse  

Using:
- Controlled randomness  
- Safeguards / bounds  
- Continuous liquidity injection  

---

## 📈 Future Improvements

- Multi-asset markets  
- Persistent accounts (database)  
- Advanced order types  
- RL-based traders  
- Distributed simulation  

---
