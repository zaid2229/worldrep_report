import frappe
from frappe import _
from frappe.utils import flt

from erpnext.accounts.report.financial_statements import (
    get_columns,
    get_filtered_list_for_consolidated_report,
    get_period_list,
)
from worldrep_report.utils import get_data_with_account_type  # Assuming this is where the custom function is located.

def execute(filters=None):
    period_list = get_period_list(
        filters.from_fiscal_year,
        filters.to_fiscal_year,
        filters.period_start_date,
        filters.period_end_date,
        filters.filter_based_on,
        filters.periodicity,
        company=filters.company,
    )

    filters.period_start_date = period_list[0]["year_start_date"]

    currency = filters.presentation_currency or frappe.get_cached_value(
        "Company", filters.company, "default_currency"
    )

    # Fetch data for Income, COGS, and Expenses using the custom function
    income = get_data_with_account_type(
        filters['company'],
        root_type="Income",
        account_type=None,  # No specific account type
        balance_must_be="Credit",
        period_list=period_list,
        filters=filters,
    )

    cogs = get_data_with_account_type(
        filters['company'],
        root_type="Expense",
        account_type="Cost of Goods Sold",  # Specify the account type for COGS
        balance_must_be="Debit",
        period_list=period_list,
        filters=filters,
    )

    expenses_excluding_cogs = get_data_with_account_type(
        filters['company'],
        root_type="Expense",
        exclude_account_type=["Cost of Goods Sold", "Tax"],  # Exclude COGS and Taxes from general expenses
        balance_must_be="Debit",
        period_list=period_list,
        filters=filters,
    )
    
    taxes_zakat = get_data_with_account_type(
        filters['company'],
        root_type="Expense",
        account_type="Tax",
        balance_must_be="Debit",
        period_list=period_list,
        filters=filters,
    )                

    # Calculate Gross Profit
    gross_profit = calculate_gross_profit(income, cogs, period_list, filters['company'], filters.get('presentation_currency'))

    # Calculate Net Profit/Loss excluding COGS in expenses
    net_profit_loss_excluding_cogs = calculate_net_profit_loss(gross_profit, expenses_excluding_cogs, period_list, filters['company'], filters.get('presentation_currency'))

    # Compile the data for the report
    data = []
    data.extend(income or [])
    
    if cogs:
        data.append({"account_name": _("Cost of Goods Sold (COGS)"), "account": _("COGS Total"), "total": True})
        data.extend(cogs or [])
        
        # Add "Total COGS"
        total_cogs = {"account_name": _("Total COGS"), "account": _("Total COGS"), "total": True}
        total_cogs_value = sum(flt(item.get(period_list[-1].key, 0)) for item in cogs if item.get('indent') == 0)
        total_cogs[period_list[-1].key] = total_cogs_value
        data.append(total_cogs)
    
    if gross_profit:
        data.append(gross_profit)
    
    # Initialize total_expense_excluding_cogs to None or a default value
    total_expense_excluding_cogs = None

    # Add expenses excluding COGS and Taxes, and calculate the total expense
    if expenses_excluding_cogs and sum(flt(item.get("total", 0)) > 0 for item in expenses_excluding_cogs):
        data.extend(expenses_excluding_cogs or [])
        
        # Calculate and display the total expenses excluding COGS and Taxes
        total_expense_excluding_cogs = {"account_name": _("Total OPEX"), "account": _("Total OPEX"), "total": True}
        total_expense_value = sum(flt(item.get(period_list[-1].key, 0)) for item in expenses_excluding_cogs if item.get('indent') == 0)
        total_expense_excluding_cogs[period_list[-1].key] = total_expense_value
        data.append(total_expense_excluding_cogs)

    # Ensure that total_expense_excluding_cogs is not None before using it
    if gross_profit and total_expense_excluding_cogs:
        profit_from_operations = {
            "account_name": _("Profit from Operations"),
            "account": _("Profit from Operations"),
            "warn_if_negative": True,
            "currency": filters.get('presentation_currency') or frappe.get_cached_value("Company", filters['company'], "default_currency"),
        }

        profit_from_operations_value = gross_profit[period_list[-1].key] - total_expense_excluding_cogs[period_list[-1].key]
        profit_from_operations[period_list[-1].key] = profit_from_operations_value
        data.append(profit_from_operations)

        
    # Add Taxes and Zakat section
    if taxes_zakat:
        taxes_zakat_total = sum(flt(tax.get(period_list[-1].key, 0)) for tax in taxes_zakat if tax.get('indent') == 0)
        taxes_zakat_data = {"account_name": _("Taxes and Zakat"), "account": _("Taxes and Zakat"), "total": True}
        taxes_zakat_data[period_list[-1].key] = taxes_zakat_total
        data.append(taxes_zakat_data)
        data.extend(taxes_zakat)
    
    if net_profit_loss_excluding_cogs and flt(net_profit_loss_excluding_cogs.get("total", 0)) > 0:
        data.append(net_profit_loss_excluding_cogs)

    # Get columns for the report
    columns = get_columns(
        filters['periodicity'], period_list, filters.get('accumulated_values'), filters['company']
    )

    # Get currency for the report
    currency = filters.get('presentation_currency') or frappe.get_cached_value(
        "Company", filters['company'], "default_currency"
    )

    # Generate report summary
    report_summary = get_report_summary(
        period_list, filters['periodicity'], income, expenses_excluding_cogs, net_profit_loss_excluding_cogs, currency, filters
    )

    return columns, data, None, None, report_summary



def calculate_gross_profit(income, cogs, period_list, company, currency=None):
    gross_profit = {
        "account_name": _("Gross Profit"),
        "account": _("Gross Profit"),
        "warn_if_negative": True,
        "currency": currency or frappe.get_cached_value("Company", company, "default_currency"),
    }

    total_gross_profit = 0

    for period in period_list:
        key = period.key

        period_income = sum(flt(income_item.get(key, 0), 3) for income_item in income if income_item.get('indent') == 0)
        period_cogs = sum(flt(cogs_item.get(key, 0), 3) for cogs_item in cogs if cogs_item.get('indent') == 0)

        gross_profit_for_period = period_income - period_cogs

        gross_profit[key] = gross_profit_for_period
        total_gross_profit += gross_profit_for_period

    gross_profit["total"] = total_gross_profit

    return gross_profit




def calculate_net_profit_loss(gross_profit, expenses, period_list, company, currency=None):
    net_profit_loss = {
        "account_name": _("Net Profit for the year"),
        "account": _("Net Profit for the year"),
        "warn_if_negative": True,
        "currency": currency or frappe.get_cached_value("Company", company, "default_currency"),
    }

    total_net_profit = 0

    for period in period_list:
        key = period.key
        
        total_gross_profit = flt(gross_profit.get(key), 3) if gross_profit else 0
        
        # Ensure expenses is not None before iterating
        total_expense = 0
        if expenses:
            total_expense = sum(flt(expense_item.get(key, 0), 3) for expense_item in expenses)

        net_profit_for_period = total_gross_profit - total_expense
        net_profit_loss[key] = net_profit_for_period

        total_net_profit += net_profit_for_period

    net_profit_loss["total"] = total_net_profit

    return net_profit_loss

def get_report_summary(period_list, periodicity, income, expense, net_profit_loss, currency, filters):
    net_income, net_expense, net_profit = 0.0, 0.0, 0.0

    if filters.get("accumulated_in_group_company"):
        period_list = get_filtered_list_for_consolidated_report(filters, period_list)

    for period in period_list:
        key = period.key
        if income:
            net_income += sum(flt(income_item.get(key, 0)) for income_item in income)
        if expense:
            net_expense += sum(flt(expense_item.get(key, 0)) for expense_item in expense)
        if net_profit_loss:
            net_profit += net_profit_loss.get(key)

    if len(period_list) == 1 and periodicity == "Yearly":
        profit_label = _("Profit This Year")
        income_label = _("Total Income This Year")
        expense_label = _("Total Expense This Year")
    else:
        profit_label = _("Net Profit")
        income_label = _("Total Income")
        expense_label = _("Total Expense")

    return [
        {"value": net_income, "label": income_label, "datatype": "Currency", "currency": currency},
        {"type": "separator", "value": "-"},
        {"value": net_expense, "label": expense_label, "datatype": "Currency", "currency": currency},
        {"type": "separator", "value": "=", "color": "blue"},
        {
            "value": net_profit,
            "indicator": "Green" if net_profit > 0 else "Red",
            "label": profit_label,
            "datatype": "Currency",
            "currency": currency,
        },
    ]
