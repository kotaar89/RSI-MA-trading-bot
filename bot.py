import time
import logging
import pandas as pd
import numpy as np

from datetime import datetime
from pybit.unified_trading import HTTP

from config import (
    API_KEY, API_SECRET, SYMBOL, INTERVAL,
    FAST_MA, SLOW_MA, RSI_PERIOD,
    RSI_BUY, RSI_SELL,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    LEVERAGE, TRADE_USDT,
    TELEGRAM_TOKEN, TELEGRAM_CHAT_ID,
    TESTNET
)
from telegram_notifier import TelegramNotifier
from backtest import run_backtest


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


class BybitFuturesBot:
    def __init__(self):
        self.client = HTTP(
            testnet=TESTNET,
            api_key=API_KEY,
            api_secret=API_SECRET,
            demo=True,
        )
        self.notifier = TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
        self.position = None 
        self.entry_price = None
        
        log.info(f"Бот запущен | {SYMBOL} | {'TESTNET' if TESTNET else 'LIVE'}")

    # Получение свечей
    def get_klines(self, limit=200) -> pd.DataFrame:
        try:
            resp = self.client.get_kline(
                category="linear",
                symbol=SYMBOL,
                interval=INTERVAL,
                limit=limit
            )
            
            data = resp["result"]["list"]
            df = pd.DataFrame(data, columns=[
                "timestamp", "open", "high", "low", "close", "volume", "turnover"
            ])
            df = df.astype({"open": float, "high": float, "low": float,
                           "close": float, "volume": float})
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
            
        except Exception as e:
            log.error(f"Ошибка получения свечей: {e}")
            raise

    # Индикаторы
    def calc_rsi(self, series: pd.Series, period: int) -> pd.Series:
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = -delta.clip(upper=0).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    def calc_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df["MA_fast"] = df["close"].rolling(FAST_MA).mean()
        df["MA_slow"] = df["close"].rolling(SLOW_MA).mean()
        df["RSI"] = self.calc_rsi(df["close"], RSI_PERIOD)

        # Сигнал: MA golden cross + RSI подтверждение
        df["signal"] = 0
        long_cond = (
            (df["MA_fast"] > df["MA_slow"]) &
            (df["MA_fast"].shift(1) <= df["MA_slow"].shift(1)) &
            (df["RSI"] < RSI_BUY)
        )
        short_cond = (
            (df["MA_fast"] < df["MA_slow"]) &
            (df["MA_fast"].shift(1) >= df["MA_slow"].shift(1)) &
            (df["RSI"] > RSI_SELL)
        )
        df.loc[long_cond, "signal"] = 1
        df.loc[short_cond, "signal"] = -1
        return df

    # Открытие позиции
    def open_position(self, side: str, price: float):
        """side: 'Buy' или 'Sell'"""
        try:
            # Установить плечо
            self.client.set_leverage(
                category="linear",
                symbol=SYMBOL,
                buyLeverage=str(LEVERAGE),
                sellLeverage=str(LEVERAGE)
            )

            qty = round(TRADE_USDT * LEVERAGE / price, 3)

            # Стоп-лосс и тейк-профит
            if side == "Buy":
                sl = round(price * (1 - STOP_LOSS_PCT), 2)
                tp = round(price * (1 + TAKE_PROFIT_PCT), 2)
            else:
                sl = round(price * (1 + STOP_LOSS_PCT), 2)
                tp = round(price * (1 - TAKE_PROFIT_PCT), 2)

            resp = self.client.place_order(
                category="linear",
                symbol=SYMBOL,
                side=side,
                orderType="Market",
                qty=str(qty),
                stopLoss=str(sl),
                takeProfit=str(tp),
                timeInForce="GoodTillCancel",
                reduceOnly=False,
                closeOnTrigger=False,
            )

            self.position = "long" if side == "Buy" else "short"
            self.entry_price = price

            msg = (
                f"{'LONG' if side == 'Buy' else 'SHORT'} открыт\n"
                f"{SYMBOL} @ {price}\n"
                f"Кол-во: {qty}\n"
                f"SL: {sl} | TP: {tp}\n"
                f"Плечо: x{LEVERAGE}"
            )
            log.info(msg)
            self.notifier.send(msg)
            return resp

        except Exception as e:
            err = f"Ошибка открытия позиции: {e}"
            log.error(err)
            self.notifier.send(err)

    # Закрытие позиции
    def close_position(self, price: float, reason: str = "Сигнал"):
        
        if not self.position:
            return
        try:
            # Отменяем все активные ордера (SL, TP)
            self.client.cancel_all_orders(category="linear", symbol=SYMBOL)
            time.sleep(0.5)  # небольшая пауза
        
            side = "Sell" if self.position == "long" else "Buy"
            qty = round(TRADE_USDT * LEVERAGE / self.entry_price, 3)

            self.client.place_order(
                category="linear",
                symbol=SYMBOL,
                side=side,
                orderType="Market",
                qty=str(qty),
                reduceOnly=True,
                timeInForce="GoodTillCancel",
            )

            pnl_pct = ((price - self.entry_price) / self.entry_price * 100)
            if self.position == "short":
                pnl_pct = -pnl_pct
            pnl_pct *= LEVERAGE

            sign = "+" if pnl_pct > 0 else ""
            msg = (
                f"Позиция закрыта ({reason})\n"
                f"{SYMBOL} @ {price}\n"
                f"PnL: {sign}{pnl_pct:.2f}%"
            )
            log.info(msg)
            self.notifier.send(msg)

            self.position = None
            self.entry_price = None

        except Exception as e:
            err = f"Ошибка закрытия позиции: {e}"
            log.error(err)
            self.notifier.send(err)

    # Получить текущую цену
    def get_price(self) -> float:
        try:
            resp = self.client.get_tickers(
                category="linear",
                symbol=SYMBOL
            )
            return float(resp["result"]["list"][0]["lastPrice"])
        except Exception as e:
            log.error(f"Ошибка получения цены: {e}")
            raise

    # Основной цикл
    def run(self):
        interval_seconds = {
            "1": 60, "3": 180, "5": 300, "15": 900,
            "30": 1800, "60": 3600, "240": 14400, "D": 86400
        }
        sleep_time = interval_seconds.get(str(INTERVAL), 3600)
        
        # Для малых таймфреймов проверяем чаще
        if str(INTERVAL) in ["1", "3", "5", "15"]:
            check_interval = 30  # проверяем каждые 30 секунд
        else:
            check_interval = sleep_time

        self.notifier.send(
            f"Бот запущен\n"
            f"{SYMBOL} | TF: {INTERVAL}m\n"
            f"RSI({RSI_PERIOD}) + MA({FAST_MA}/{SLOW_MA})\n"
            f"Депозит на сделку: {TRADE_USDT} USDT | x{LEVERAGE}\n"
            f"Проверка: каждые {check_interval}с"
        )

        last_log_time = 0
        consecutive_errors = 0

        while True:
            try:
                df = self.get_klines()
                df = self.calc_signals(df)

                last = df.iloc[-1]
                price = self.get_price()
                signal = df["signal"].iloc[-2] 
                
                signal_price = df["close"].iloc[-2]
                
                if abs(price - signal_price) / signal_price > 0.005:  # 0.5%
                    log.warning(f"Цена ушла: сигнал {signal_price}, рынок {price}")
                    continue  # не входим


                # Логирование (не чаще чем раз в 5 минут для больших ТФ)
                if time.time() - last_log_time > 300:
                    log.info(
                        f"{SYMBOL} | Price: {price:.2f} | "
                        f"RSI: {last['RSI']:.1f} | "
                        f"MA_fast: {last['MA_fast']:.2f} | MA_slow: {last['MA_slow']:.2f} | "
                        f"Signal: {signal} | Position: {self.position}"
                    )
                    last_log_time = time.time()

                # Логика входа/выхода
                if signal == 1 and self.position != "long":
                    if self.position == "short":
                        self.close_position(price, "Смена сигнала")
                    self.open_position("Buy", price)

                elif signal == -1 and self.position != "short":
                    if self.position == "long":
                        self.close_position(price, "Смена сигнала")
                    self.open_position("Sell", price)

                consecutive_errors = 0
                time.sleep(check_interval)

            except KeyboardInterrupt:
                log.info("Бот остановлен вручную")
                self.notifier.send("Бот остановлен")
                break
                
            except Exception as e:
                consecutive_errors += 1
                err = f"Ошибка в основном цикле ({consecutive_errors}): {e}"
                log.error(err)
                
                if consecutive_errors >= 5:
                    self.notifier.send(f"Критическая ошибка: {e}. Бот останавливается.")
                    break
                    
                if consecutive_errors >= 3:
                    log.info("Переподключение...")
                    time.sleep(60)
                else:
                    time.sleep(30)


# Точка входа
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "backtest":
        run_backtest()
    else:
        bot = BybitFuturesBot()
        bot.run()