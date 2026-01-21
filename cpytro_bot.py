import os
import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime
from binance.client import Client
from binance.enums import *
import talib

# Configuration
API_KEY = 'your_api_key'
API_SECRET = 'your_api_secret'
client = Client(API_KEY, API_SECRET)

class CPYTRO_BOT:
    def __init__(self):
        self.symbols = self.get_all_symbols()
        self.investment_percentage = 100  # ใช้เงินทั้งหมด
        self.tp_percentage = 6  # ตั้ง TP 6%
        
    def get_all_symbols(self):
        """ดึงข้อมูลเหรียญทั้งหมดจาก Binance"""
        exchange_info = client.get_exchange_info()
        symbols = [symbol['symbol'] for symbol in exchange_info['symbols'] 
                  if symbol['symbol'].endswith('USDT')]
        return symbols
    
    def fetch_ohlcv(self, symbol, timeframe, limit=100):
        """ดึงข้อมูล OHLCV"""
        interval_mapping = {
            '5m': Client.KLINE_INTERVAL_5MINUTE,
            '15m': Client.KLINE_INTERVAL_15MINUTE,
            '1h': Client.KLINE_INTERVAL_1HOUR,
            '4h': Client.KLINE_INTERVAL_4HOUR
        }
        
        klines = client.get_klines(
            symbol=symbol,
            interval=interval_mapping[timeframe],
            limit=limit
        )
        
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base', 'taker_buy_quote', 'ignore'
        ])
        
        df['close'] = df['close'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        return df
    
    def calculate_indicators(self, df):
        """คำนวณตัวบ่งชี้ทั้งหมด"""
        # RSI
        df['rsi'] = talib.RSI(df['close'], timeperiod=14)
        
        # MACD
        macd, signal, hist = talib.MACD(df['close'])
        df['macd'] = macd
        df['macd_signal'] = signal
        
        # Bollinger Bands
        upper, middle, lower = talib.BBANDS(df['close'])
        df['bb_upper'] = upper
        df['bb_middle'] = middle
        df['bb_lower'] = lower
        
        # EMA
        df['ema_9'] = talib.EMA(df['close'], timeperiod=9)
        df['ema_21'] = talib.EMA(df['close'], timeperiod=21)
        df['ema_50'] = talib.EMA(df['close'], timeperiod=50)
        df['ema_200'] = talib.EMA(df['close'], timeperiod=200)
        
        return df
    
    def analyze_timeframes(self, symbol):
        """วิเคราะห์หลายไทม์เฟรม"""
        timeframes = ['5m', '15m', '1h', '4h']
        analysis = {}
        
        for tf in timeframes:
            df = self.fetch_ohlcv(symbol, tf)
            df = self.calculate_indicators(df)
            
            # เก็บข้อมูลล่าสุด
            latest = df.iloc[-1]
            prev = df.iloc[-2]
            
            analysis[tf] = {
                'rsi': latest['rsi'],
                'macd_bullish': latest['macd'] > latest['macd_signal'],
                'price_vs_bb': (latest['close'] - latest['bb_lower']) / 
                               (latest['bb_upper'] - latest['bb_lower']) * 100,
                'trend': 'bullish' if latest['ema_9'] > latest['ema_21'] else 'bearish',
                'volume_spike': latest['volume'] > df['volume'].rolling(20).mean().iloc[-1] * 1.5
            }
            
        return analysis
    
    def check_entry_signal(self, analysis):
        """ตรวจสอบสัญญาณเข้า"""
        conditions = []
        
        # เงื่อนไขจาก H4
        if analysis['4h']['trend'] == 'bullish':
            conditions.append('h4_bullish')
        
        # เงื่อนไขจาก M5/M15 สำหรับ oversold
        if analysis['5m']['rsi'] < 30 or analysis['15m']['rsi'] < 30:
            conditions.append('oversold')
        
        # MACD bullish crossover
        macd_bullish = sum([1 for tf in ['5m', '15m', '1h'] 
                           if analysis[tf]['macd_bullish']]) >= 2
        if macd_bullish:
            conditions.append('macd_bullish')
        
        # Price near lower BB
        if analysis['5m']['price_vs_bb'] < 20:
            conditions.append('near_lower_bb')
        
        # Volume spike
        if analysis['5m']['volume_spike']:
            conditions.append('volume_spike')
        
        # ต้องผ่านอย่างน้อย 4 ใน 5 เงื่อนไข
        return len(conditions) >= 4
    
    def execute_trade(self, symbol):
        """ทำการเทรด"""
        try:
            # ตรวจสอบยอดเงิน
            balance = client.get_asset_balance(asset='USDT')
            usdt_balance = float(balance['free'])
            
            # ราคาปัจจุบัน
            ticker = client.get_symbol_ticker(symbol=symbol)
            current_price = float(ticker['price'])
            
            # คำนวณจำนวนที่จะซื้อ
            amount = (usdt_balance * 0.99) / current_price  # ใช้ 99% ของยอดเงิน
            
            # คำสั่งซื้อแบบตลาด
            order = client.create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=round(amount, self.get_precision(symbol))
            )
            
            print(f"[{datetime.now()}] ซื้อ {symbol} จำนวน {amount:.4f} ที่ราคา {current_price}")
            
            # ตั้ง TP 6%
            tp_price = current_price * 1.06
            
            # สร้าง OCO Order (Take Profit)
            client.create_oco_order(
                symbol=symbol,
                side=SIDE_SELL,
                quantity=round(amount, self.get_precision(symbol)),
                stopPrice=round(current_price * 0.99, 2),
                stopLimitPrice=round(current_price * 0.99, 2),
                price=round(tp_price, 2),
                stopLimitTimeInForce=TIME_IN_FORCE_GTC
            )
            
            print(f"ตั้ง TP ที่ {tp_price:.4f} (+6%)")
            
        except Exception as e:
            print(f"Error executing trade: {e}")
    
    def get_precision(self, symbol):
        """หาความแม่นยำของเหรียญ"""
        info = client.get_symbol_info(symbol)
        step_size = info['filters'][2]['stepSize']
        precision = len(step_size.split('.')[1].rstrip('0'))
        return precision
    
    def run(self):
        """รันบอท"""
        print(f"เริ่มต้นบอท cpytro เวลา {datetime.now()}")
        print(f"ติดตามเหรียญทั้งหมด: {len(self.symbols)} เหรียญ")
        
        while True:
            try:
                for symbol in self.symbols:
                    try:
                        print(f"\nวิเคราะห์ {symbol}...")
                        
                        # วิเคราะห์หลายไทม์เฟรม
                        analysis = self.analyze_timeframes(symbol)
                        
                        # ตรวจสอบสัญญาณ
                        if self.check_entry_signal(analysis):
                            print(f"พบสัญญาณเข้าเทรดสำหรับ {symbol}!")
                            self.execute_trade(symbol)
                        
                        time.sleep(1)  # รอระหว่างการตรวจสอบแต่ละเหรียญ
                        
                    except Exception as e:
                        print(f"Error analyzing {symbol}: {e}")
                        continue
                
                print(f"\nรอบการตรวจสอบเสร็จสิ้น {datetime.now()}")
                print("รอ 5 นาทีก่อนรอบต่อไป...")
                time.sleep(300)  # รอ 5 นาที
                
            except KeyboardInterrupt:
                print("\nหยุดบอท...")
                sys.exit()

# Install requirements สำหรับ Termux
def setup_termux():
    print("ติดตั้งแพ็คเกจที่จำเป็น...")
    os.system('pkg update && pkg upgrade -y')
    os.system('pkg install python -y')
    os.system('pip install python-binance pandas numpy TA-Lib')
    
    print("ติดตั้ง TA-Lib...")
    os.system('pkg install clang -y')
    os.system('pip install TA-Lib')

if __name__ == "__main__":
    # สำหรับ Termux: รัน setup ก่อนครั้งแรก
    # setup_termux()
    
    bot = CPYTRO_BOT()
    bot.run()
