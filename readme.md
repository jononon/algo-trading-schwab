Algorithmic Trading Bot
=======================

This bot makes use of the Schwab API to algorithmically trade stocks. 
The bot will run at market open daily and will create a target portfolio based on the strategy below.
It will then execute trades to bring the current portfolio in line with the target portfolio.

# Trading Strategy
Is 60 day cumulative return of AGG (US Aggregate Bond ETF) > 60 day cumulative return of BIL (1-3 Month T-Bill ETF)?
> Put risk on.
> 
> From the following ETFs, invest evenly in the two with the lowest 10 day relative strength:
> - SOXL (Direxion Daily Semiconductor Bull 3X Shares)
> - TQQQ (ProShares UltraPro 3X QQQ)
> - UPRO (ProShares UltraPro 3X S&P 500)
> - TECL (Direxion Daily Technology Bull 3X Shares)

Is 20 day cumulative return of TLT (20+ Year Treasury Bond ETF) < 20 day cumulative return of BIL (1-3 Month T-Bill ETF)?
> Put risk off, rising interest rates
> 
> Invest 50% in UUP (Invesco DB US Dollar Index Bullish Fund) and 50% in whichever of the following two ETFs has the lowest 20 day relative strength:
> - QID (ProShares UltraShort QQQ)
> - TBF (ProShares Short 20+ Year Treasury)

Otherwise
> Put risk off, falling interest rates
> 
> Invest evenly in the following ETFs:
> - UGL (ProShares Ultra Gold)
> - TMF (Direxion Daily 20+ Year Treasury Bull 3X Shares)
> - BTAL (AGFiQ US Market Neutral Anti-Beta Fund)
> - XLP (Consumer Staples Select Sector SPDR Fund)

This strategy is based on the following strategy from Composer: https://app.composer.trade/symphony/xDsLkk2PAlXio3qTs1KY/details

# Infrastructure
This bot is written as a Python lambda in AWS using the serverless framework.
All components are defined in the serverless.yml file.
The following AWS services are used:
- Cloudwatch: Logging and alarming for bot failures
- DynamoDB: Storing trade information, persistent storage for the bot
- Lambda: Running the bot
- SSM: Storing access keys for Schwab

This product makes use of the Schwab Individual Developer API. It is not endorsed by Schwab and is not guaranteed to work. Use at your own risk.

This bot runs in us-west-1 in order to be as close as possible to Schwab's servers which are in Phoenix, AZ.