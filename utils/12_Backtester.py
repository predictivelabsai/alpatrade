import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pytz
from utils.back_test_util import run_backtest
from utils.db.news_db_util import get_news_df_date_range
import os
import plotly.graph_objects as go

st.title("Strategy Backtester")

# Parameters section
st.header("Parameters")

# Date Range Selection
col1, col2 = st.columns(2)
with col1:
    start_date = st.date_input(
        "Start Date",
        value=datetime.now(pytz.UTC) - timedelta(days=30),
        key="start_date"
    )
with col2:
    end_date = st.date_input(
        "End Date",
        value=datetime.now(pytz.UTC),
        key="end_date"
    )

# Convert dates to datetime with UTC timezone
start_datetime = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=pytz.UTC)
end_datetime = datetime.combine(end_date, datetime.max.time()).replace(tzinfo=pytz.UTC)

# Initial Capital and Position Size
col3, col4 = st.columns(2)
with col3:
    initial_capital = st.number_input("Initial Capital ($)", value=10000, step=1000)
with col4:
    position_size = st.number_input("Position Size (%)", value=10, min_value=1, max_value=100)

# Take Profit and Stop Loss
col5, col6 = st.columns(2)
with col5:
    take_profit = st.number_input("Take Profit (%)", value=1.0, step=0.1)
with col6:
    stop_loss = st.number_input("Stop Loss (%)", value=0.5, step=0.1)

# Publisher Selection (Single select dropdown)
available_publishers = [
    "globenewswire_country_fi",
    "globenewswire_country_dk",
    "globenewswire_biotech",
    "globenewswire_country_no",
    "globenewswire_country_lt",
    "globenewswire_country_lv",
    "globenewswire_country_is",
    "baltics",
    "globenewswire_country_se",
    "globenewswire_country_ee",
    "omx",
    "euronext"
]

selected_publisher = st.selectbox(
    "Select Publisher",
    options=available_publishers,
    index=2  # Default to globenewswire_biotech
)

# Event Selection with accuracy scores
available_events = {
    "changes_in_companys_own_shares": 88.89,
    "business_contracts": 83.33,
    "patents": 83.33,
    "shares_issue": 81.82,
    "corporate_action": 81.82,
    "licensing_agreements": 80.00,
    "major_shareholder_announcements": 75.00,
    "financial_results": 73.08,
    "financing_agreements": 71.43,
    "clinical_study": 69.49,
    #"bond_fixing": 66.67,
    "dividend_reports_and_estimates": 66.67,
    "management_changes": 65.00,
    #"conference_call_webinar": 64.00,
    "partnerships": 63.64,
    "earnings_releases_and_operating_result": 61.54,
    "regulatory_filings": 61.54,
    "product_services_announcement": 60.00
}

# Create options with accuracy scores
event_options = [f"{event} ({accuracy}%)" for event, accuracy in available_events.items()]
selected_events = st.multiselect(
    "Select Events",
    options=event_options,
    default=event_options  # Default to all events
)

# Extract event names without accuracy scores
selected_event_names = [event.split(" (")[0] for event in selected_events]

if st.button("Run Backtest"):
    if start_datetime > end_datetime:
        st.error("Start date must be before end date")
    else:
        with st.spinner("Running backtest..."):
            # Get news data for the selected date range
            news_df = get_news_df_date_range(
                publishers=[selected_publisher],  # Pass as list
                start_date=start_datetime,
                end_date=end_datetime
            )
            
            # Filter by selected events
            if selected_event_names:
                news_df = news_df[news_df['event'].isin(selected_event_names)]
            
            # Run backtest
            results = run_backtest(
                news_df=news_df,
                initial_capital=initial_capital,
                position_size=position_size/100,
                take_profit=take_profit/100,
                stop_loss=stop_loss/100
            )
            
            if results is None:
                st.error("No trades were generated during the backtest period. This could be due to:\n"
                        "1. No news data available for the selected date range\n"
                        "2. Missing price data for the news events\n"
                        "3. No valid trades meeting the criteria")
            else:
                trades_df, metrics = results
                
                # Display metrics
                st.header("Backtest Results")
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Return", f"{metrics['total_return']:.1f}%")
                col1.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
                col2.metric("Total PnL", f"${metrics['total_pnl']:,.0f}")
                col2.metric("Total Trades", metrics['total_trades'])
                col3.metric("Ann. Return", f"{metrics['annualized_return']:.1f}%")
                
                # Create and display equity curve
                st.subheader("Equity Curve")
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=trades_df['exit_time'],
                    y=trades_df['capital_after'],
                    mode='lines+markers',
                    name='Portfolio Value'
                ))
                fig.update_layout(
                    title='Portfolio Value Over Time',
                    xaxis_title='Date',
                    yaxis_title='Portfolio Value ($)',
                    hovermode='x unified'
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Display trade history
                st.subheader("Trade History")
                st.dataframe(trades_df)
                
                # Save trades to CSV
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                csv_path = f"data/trades_{timestamp}.csv"
                os.makedirs("data", exist_ok=True)
                trades_df.to_csv(csv_path, index=False)
                st.success(f"Trade history saved to {csv_path}") 