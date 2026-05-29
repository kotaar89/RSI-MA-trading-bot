"""
usage: python bot.py backtest
        python backtest.py 180         # download 180 days
        python backtest.py 90 --force  # force redownload
"""

import sys
import pandas as pd
import numpy as np
from config import (
    SYMBOL, INTERVAL, FAST_MA, SLOW_MA, RSI_PERIOD,
    RSI_BUY, RSI_SELL,
    STOP_LOSS_PCT, TAKE_PROFIT_PCT,
    LEVERAGE, TRADE_USDT
)
from data_loader import load_or_download

# комиссии
TAKER_FEE = 0.00055   
SLIPPAGE  = 0.0002    


def calc_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def run_backtest(days: int = 90, force_download: bool = False):
    print("\n" + "="*58)
    print("  БЭКТЕСТ — RSI + MA COMBO STRATEGY")
    print(f"  {SYMBOL} | TF: {INTERVAL}m | {days} дней")
    print("="*58)

    df = load_or_download(SYMBOL, INTERVAL, days, force_download)

    if df.empty:
        print("Не удалось получить данные")
        return None

    # indicators
    df["MA_fast"] = df["close"].rolling(FAST_MA).mean()
    df["MA_slow"] = df["close"].rolling(SLOW_MA).mean()
    df["RSI"]     = calc_rsi(df["close"], RSI_PERIOD)

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
    df.loc[long_cond, "signal"]  = 1
    df.loc[short_cond, "signal"] = -1
    df = df.dropna().reset_index(drop=True)

    # trade simulation
    trades      = []
    position    = None
    entry_price = None
    entry_idx   = None

    def close_trade(exit_price, reason, i):
        nonlocal position, entry_price, entry_idx
        fee_pct = (entry_price + exit_price) * TAKER_FEE * LEVERAGE / entry_price * 100


        if position == "long":
            raw_pnl = (exit_price - entry_price) / entry_price * LEVERAGE * 100
        else:
            raw_pnl = (entry_price - exit_price) / entry_price * LEVERAGE * 100

        net_pnl = raw_pnl - fee_pct 

        trades.append({
            "type":       position,
            "entry":      entry_price,
            "exit":       exit_price,
            "pnl_pct":    net_pnl,
            "reason":     reason,
            "bars":       i - entry_idx,
            "entry_time": df["timestamp"].iloc[entry_idx],
            "exit_time":  df["timestamp"].iloc[i],
        })
        position    = None
        entry_price = None
        entry_idx   = None

    for i in range(1, len(df)):
        price  = df["close"].iloc[i]
        signal = df["signal"].iloc[i - 1]

        # SL/TP check
        if position == "long":
            sl = entry_price * (1 - STOP_LOSS_PCT)
            tp = entry_price * (1 + TAKE_PROFIT_PCT)
            if price <= sl:
                close_trade(sl, "SL", i); continue
            elif price >= tp:
                close_trade(tp, "TP", i); continue

        elif position == "short":
            sl = entry_price * (1 + STOP_LOSS_PCT)
            tp = entry_price * (1 - TAKE_PROFIT_PCT)
            if price >= sl:
                close_trade(sl, "SL", i); continue
            elif price <= tp:
                close_trade(tp, "TP", i); continue

        # signal trade open
        if signal == 1 and position != "long":
            if position == "short":
                close_trade(price, "Сигнал", i)
            position    = "long"
            entry_price = price * (1 + SLIPPAGE)
            entry_idx   = i

        elif signal == -1 and position != "short":
            if position == "long":
                close_trade(price, "Сигнал", i)
            position    = "short"
            entry_price = price * (1 - SLIPPAGE)
            entry_idx   = i

    # stats
    if not trades:
        print("Сделок не найдено. Попробуйте изменить параметры.")
        return None

    tdf = pd.DataFrame(trades)
    total    = len(tdf)
    wins     = len(tdf[tdf["pnl_pct"] > 0])
    losses   = total - wins
    win_rate = wins / total * 100

    avg_win  = tdf[tdf["pnl_pct"] > 0]["pnl_pct"].mean() if wins   else 0
    avg_loss = tdf[tdf["pnl_pct"] <= 0]["pnl_pct"].mean() if losses else 0

    total_pnl_pct  = tdf["pnl_pct"].sum()
    total_pnl_usdt = TRADE_USDT * total_pnl_pct / 100

    cumulative   = tdf["pnl_pct"].cumsum()
    max_drawdown = (cumulative - cumulative.cummax()).min()

    profit_factor = (
        abs(tdf[tdf["pnl_pct"] > 0]["pnl_pct"].sum()) /
        abs(tdf[tdf["pnl_pct"] <= 0]["pnl_pct"].sum())
        if losses else float("inf")
    )

    sl_count  = len(tdf[tdf["reason"] == "SL"])
    tp_count  = len(tdf[tdf["reason"] == "TP"])
    sig_count = len(tdf[tdf["reason"] == "Сигнал"])

    print(f"\nПериод:           {df['timestamp'].iloc[0].date()} → {df['timestamp'].iloc[-1].date()}")
    print(f"Свечей:           {len(df)}")
    print()
    print(f"Всего сделок:     {total}")
    print(f"Прибыльных:       {wins} ({win_rate:.1f}%)")
    print(f"Убыточных:        {losses} ({100 - win_rate:.1f}%)")
    print()
    print(f"Средняя прибыль:  {avg_win:+.2f}%")
    print(f"Средний убыток:   {avg_loss:+.2f}%")
    print(f"Profit Factor:    {profit_factor:.2f}")
    print()
    print(f"Общий PnL:        {total_pnl_pct:+.2f}% ({total_pnl_usdt:+.2f} USDT)")
    print(f"Макс. просадка:   {max_drawdown:.2f}%")
    print()
    print(f"Закрыто по SL:    {sl_count}")
    print(f"Закрыто по TP:    {tp_count}")
    print(f"Закрыто сигналом: {sig_count}")

    print("\nПоследние 5 сделок:")
    print(f"{'Тип':<7}{'Вход':<12}{'Выход':<12}{'PnL%':<10}{'Причина':<10}{'Дата входа'}")
    print("-" * 62)
    for _, t in tdf.tail(5).iterrows():
        mark = "+" if t["pnl_pct"] > 0 else "-"
        dt = t["entry_time"].strftime("%m-%d %H:%M")
        print(f"{mark} {t['type']:<6}{t['entry']:<12.2f}{t['exit']:<12.2f}"
              f"{t['pnl_pct']:+.2f}%    {t['reason']:<10}{dt}")

    print("=" * 58 + "\n")
    return tdf


if __name__ == "__main__":
    days  = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    force = "--force" in sys.argv
    run_backtest(days=days, force_download=force)