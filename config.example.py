"""
paste your API keys and rename file to "config.py"
"""

#API bybit 
API_KEY    = "your_api_key"
API_SECRET = "your_secret_api_key"

# telegram 
TELEGRAM_TOKEN   = "your_telegram_bot_api"
TELEGRAM_CHAT_ID = "chat_id_with_you @userinfobot"

TESTNET    = False   

SYMBOL   = "BTCUSDT"   # trading pair symbol
INTERVAL = "30"        # timeframe in minutes

#rsi + ma strategy
FAST_MA    = 20    
SLOW_MA    = 50    
RSI_PERIOD = 14    
RSI_BUY    = 55    
RSI_SELL   = 45    

# risk management
STOP_LOSS_PCT   = 0.01  
TAKE_PROFIT_PCT = 0.03   
LEVERAGE        = 5      
TRADE_USDT      = 50     


