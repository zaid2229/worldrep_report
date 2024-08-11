import frappe
from frappe.utils import flt
from erpnext.accounts.utils import get_fiscal_year
import functools  # Importing functools module
import math
import re

from frappe import _
from frappe.utils import (
	add_days,
	add_months,
	cint,
	cstr,
	flt,
	formatdate,
	get_first_day,
	getdate,
	today,
)

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
	get_dimension_with_children,
)
from erpnext.accounts.report.utils import convert_to_presentation_currency, get_currency


def filter_accounts(accounts, depth=20):
    parent_children_map = {}
    accounts_by_name = {}
    for d in accounts:
        accounts_by_name[d.name] = d
        parent_children_map.setdefault(d.parent_account or None, []).append(d)

    filtered_accounts = []

    def add_to_list(parent, level):
        if level < depth:
            children = parent_children_map.get(parent) or []
            sort_accounts(children, is_root=True if parent is None else False)

            for child in children:
                child.indent = level
                filtered_accounts.append(child)
                add_to_list(child.name, level + 1)

    add_to_list(None, 0)

    return filtered_accounts, accounts_by_name, parent_children_map

def sort_accounts(accounts, is_root=False, key="name"):
    """Sort root types as Asset, Liability, Equity, Income, Expense"""

    def compare_accounts(a, b):
        if re.split(r"\W+", a[key])[0].isdigit():
            # if chart of accounts is numbered, then sort by number
            return int(a[key] > b[key]) - int(a[key] < b[key])
        elif is_root:
            if a.report_type != b.report_type and a.report_type == "Balance Sheet":
                return -1
            if a.root_type != b.root_type and a.root_type == "Asset":
                return -1
            if a.root_type == "Liability" and b.root_type == "Equity":
                return -1
            if a.root_type == "Income" and b.root_type == "Expense":
                return -1
        else:
            # sort by key (number) or name
            return int(a[key] > b[key]) - int(a[key] < b[key])
        return 1

    accounts.sort(key=functools.cmp_to_key(compare_accounts))


def get_data_with_account_type(
    company,
    root_type=None,
    account_type=None,
    balance_must_be=None,
    period_list=None,
    filters=None,
    accumulated_values=1,
    only_current_fiscal_year=True,
    ignore_closing_entries=False,
    ignore_accumulated_values_for_fy=False,
    total=True,
    exclude_account_type=None,  # New parameter for excluding specific account types
):
    """
    Custom function to fetch data with filtering by both root_type and account_type.
    """
    # Pass the exclude_account_type to the function
    accounts = get_accounts_with_account_type(company, root_type, account_type, exclude_account_type)
    if not accounts:
        return None

    accounts, accounts_by_name, parent_children_map = filter_accounts(accounts)

    company_currency = frappe.get_cached_value("Company", company, "default_currency")

    gl_entries_by_account = {}
    for root in frappe.db.sql(
        """select lft, rgt from tabAccount
            where root_type=%s and ifnull(parent_account, '') = ''""",
        root_type,
        as_dict=1,
    ):

        set_gl_entries_by_account(
            company,
            period_list[0]["year_start_date"] if only_current_fiscal_year else None,
            period_list[-1]["to_date"],
            root.lft,
            root.rgt,
            filters,
            gl_entries_by_account,
            ignore_closing_entries=ignore_closing_entries,
            root_type=root_type,
            account_type=account_type,
        )

    calculate_values(
        accounts_by_name,
        gl_entries_by_account,
        period_list,
        accumulated_values,
        ignore_accumulated_values_for_fy,
    )
    accumulate_values_into_parents(accounts, accounts_by_name, period_list)
    out = prepare_data(accounts, balance_must_be, period_list, company_currency)
    out = filter_out_zero_value_rows(out, parent_children_map)

    if out and total:
        add_total_row(out, root_type, balance_must_be, period_list, company_currency)

    return out

def get_accounts_with_account_type(company, root_type=None, account_type=None, exclude_account_type=None):
    """
    Fetch accounts based on company, root_type, account_type, and optionally exclude specific account types.
    """
    conditions = []
    params = [company]

    if root_type:
        conditions.append("root_type=%s")
        params.append(root_type)

    if account_type:
        conditions.append("account_type=%s")
        params.append(account_type)

    if exclude_account_type:
        if isinstance(exclude_account_type, list):
            placeholders = ', '.join(['%s'] * len(exclude_account_type))
            conditions.append(f"account_type NOT IN ({placeholders})")
            params.extend(exclude_account_type)
        else:
            conditions.append("account_type <> %s")
            params.append(exclude_account_type)

    query = f"""
        select name, account_number, parent_account, lft, rgt, root_type, report_type, account_name, include_in_gross, account_type, is_group, lft, rgt
        from `tabAccount`
        where company=%s {"and " + " and ".join(conditions) if conditions else ""}
        order by lft
    """

    return frappe.db.sql(query, tuple(params), as_dict=True)

def set_gl_entries_by_account(
    company,
    from_date,
    to_date,
    root_lft,
    root_rgt,
    filters,
    gl_entries_by_account,
    ignore_closing_entries=False,
    ignore_opening_entries=False,
    root_type=None,
    account_type=None,
):
    """
    Modified function to filter GL entries by root_type and account_type.
    """
    gl_entries = []

    account_filters = {
        "company": company,
        "is_group": 0,
        "lft": (">=", root_lft),
        "rgt": ("<=", root_rgt),
    }

    if root_type:
        account_filters.update({"root_type": root_type})

    if account_type:
        account_filters.update({"account_type": account_type})

    accounts_list = frappe.db.get_all(
        "Account",
        filters=account_filters,
        pluck="name",
    )

    if accounts_list:
        gl_entries += get_accounting_entries(
            "GL Entry",
            from_date,
            to_date,
            accounts_list,
            filters,
            ignore_closing_entries,
            ignore_opening_entries=ignore_opening_entries,
        )

        if filters and filters.get("presentation_currency"):
            convert_to_presentation_currency(gl_entries, get_currency(filters))

        for entry in gl_entries:
            gl_entries_by_account.setdefault(entry.account, []).append(entry)

    return gl_entries_by_account


def get_accounting_entries(
    doctype,
    from_date,
    to_date,
    accounts,
    filters,
    ignore_closing_entries,
    period_closing_voucher=None,
    ignore_opening_entries=False,
):
    """
    Function to fetch GL accounting entries with additional conditions.
    """
    gl_entry = frappe.qb.DocType(doctype)
    query = (
        frappe.qb.from_(gl_entry)
        .select(
            gl_entry.account,
            gl_entry.debit,
            gl_entry.credit,
            gl_entry.debit_in_account_currency,
            gl_entry.credit_in_account_currency,
            gl_entry.account_currency,
        )
        .where(gl_entry.company == filters.company)
    )

    if doctype == "GL Entry":
        query = query.select(gl_entry.posting_date, gl_entry.is_opening, gl_entry.fiscal_year)
        query = query.where(gl_entry.is_cancelled == 0)
        query = query.where(gl_entry.posting_date <= to_date)

        if ignore_opening_entries:
            query = query.where(gl_entry.is_opening == "No")
    else:
        query = query.select(gl_entry.closing_date.as_("posting_date"))
        query = query.where(gl_entry.period_closing_voucher == period_closing_voucher)

    query = apply_additional_conditions(doctype, query, from_date, ignore_closing_entries, filters)
    query = query.where(gl_entry.account.isin(accounts))

    entries = query.run(as_dict=True)

    return entries


def apply_additional_conditions(doctype, query, from_date, ignore_closing_entries, filters):
    gl_entry = frappe.qb.DocType(doctype)
    accounting_dimensions = get_accounting_dimensions(as_list=False)

    if ignore_closing_entries:
        if doctype == "GL Entry":
            query = query.where(gl_entry.voucher_type != "Period Closing Voucher")
        else:
            query = query.where(gl_entry.is_period_closing_voucher_entry == 0)

    if from_date and doctype == "GL Entry":
        query = query.where(gl_entry.posting_date >= from_date)

    if filters:
        if filters.get("project"):
            if not isinstance(filters.get("project"), list):
                filters.project = frappe.parse_json(filters.get("project"))

            query = query.where(gl_entry.project.isin(filters.project))

        if filters.get("cost_center"):
            filters.cost_center = get_cost_centers_with_children(filters.cost_center)
            query = query.where(gl_entry.cost_center.isin(filters.cost_center))

        if filters.get("include_default_book_entries"):
            company_fb = frappe.get_cached_value("Company", filters.company, "default_finance_book")

            if filters.finance_book and company_fb and cstr(filters.finance_book) != cstr(company_fb):
                frappe.throw(_("To use a different finance book, please uncheck 'Include Default FB Entries'"))

            query = query.where(
                (gl_entry.finance_book.isin([cstr(filters.finance_book), cstr(company_fb), ""]))
                | (gl_entry.finance_book.isnull())
            )
        else:
            query = query.where(
                (gl_entry.finance_book.isin([cstr(filters.finance_book), ""]))
                | (gl_entry.finance_book.isnull())
            )

    if accounting_dimensions:
        for dimension in accounting_dimensions:
            if filters.get(dimension.fieldname):
                if frappe.get_cached_value("DocType", dimension.document_type, "is_tree"):
                    filters[dimension.fieldname] = get_dimension_with_children(
                        dimension.document_type, filters.get(dimension.fieldname)
                    )

                query = query.where(gl_entry[dimension.fieldname].isin(filters[dimension.fieldname]))

    return query


def calculate_values(
    accounts_by_name,
    gl_entries_by_account,
    period_list,
    accumulated_values,
    ignore_accumulated_values_for_fy,
):
    """
    Calculate the values of accounts for each period.
    """
    for entries in gl_entries_by_account.values():
        for entry in entries:
            account = accounts_by_name.get(entry.account)
            if not account:
                # Log the error without raising an exception
                frappe.log_error(
                    message=_("Could not retrieve information for {0}.").format(entry.account),
                    title=_("Missing Account Error"),
                )
                continue  # Skip processing this entry if account is not found

            for period in period_list:
                # check if posting date is within the period
                if entry.posting_date <= period.to_date:
                    if (accumulated_values or entry.posting_date >= period.from_date) and (
                        not ignore_accumulated_values_for_fy or entry.fiscal_year == period.to_date_fiscal_year
                    ):
                        account[period.key] = account.get(period.key, 0.0) + flt(entry.debit) - flt(entry.credit)

            if entry.posting_date < period_list[0].year_start_date:
                account["opening_balance"] = account.get("opening_balance", 0.0) + flt(entry.debit) - flt(entry.credit)




def accumulate_values_into_parents(accounts, accounts_by_name, period_list):
    """
    Accumulate the values from child accounts into their parent accounts.
    """
    for account in reversed(accounts):
        if account.parent_account:
            for period in period_list:
                accounts_by_name[account.parent_account][period.key] = accounts_by_name[account.parent_account].get(
                    period.key, 0.0
                ) + account.get(period.key, 0.0)

            accounts_by_name[account.parent_account]["opening_balance"] = accounts_by_name[account.parent_account].get(
                "opening_balance", 0.0
            ) + account.get("opening_balance", 0.0)


def prepare_data(accounts, balance_must_be, period_list, company_currency):
    """
    Prepare the data for display in the report.
    """
    data = []
    year_start_date = period_list[0]["year_start_date"].strftime("%Y-%m-%d")
    year_end_date = period_list[-1]["year_end_date"].strftime("%Y-%m-%d")

    for account in accounts:
        # add to output
        has_value = False
        total = 0
        row = frappe._dict(
            {
                "account": _(account.name),
                "parent_account": _(account.parent_account) if account.parent_account else "",
                "indent": flt(account.indent),
                "year_start_date": year_start_date,
                "year_end_date": year_end_date,
                "currency": company_currency,
                "include_in_gross": account.include_in_gross,
                "account_type": account.account_type,
                "is_group": account.is_group,
                "opening_balance": account.get("opening_balance", 0.0) * (1 if balance_must_be == "Debit" else -1),
                "account_name": (
                    "%s - %s" % (_(account.account_number), _(account.account_name))
                    if account.account_number
                    else _(account.account_name)
                ),
            }
        )
        for period in period_list:
            if account.get(period.key) and balance_must_be == "Credit":
                # change sign based on Debit or Credit, since calculation is done using (debit - credit)
                account[period.key] *= -1

            row[period.key] = flt(account.get(period.key, 0.0), 3)

            if abs(row[period.key]) >= 0.005:
                # ignore zero values
                has_value = True
                total += flt(row[period.key])

        row["has_value"] = has_value
        row["total"] = total
        data.append(row)

    return data


def filter_out_zero_value_rows(data, parent_children_map, show_zero_values=False):
    """
    Filter out rows with zero values, unless they have children with non-zero values.
    """
    data_with_value = []
    for row in data:
        if show_zero_values or row.get("has_value"):
            data_with_value.append(row)
        else:
            # show group with zero balance, if there are balances against child
            children = [child.name for child in parent_children_map.get(row.get("account")) or []]
            if children:
                for child_row in data:
                    if child_row.get("account") in children and child_row.get("has_value"):
                        data_with_value.append(row)
                        break

    return data_with_value


def add_total_row(out, root_type, balance_must_be, period_list, company_currency):
    """
    Add a total row at the end of the report for the specified root type (e.g., Income, Expense).
    """
    total_row = {
        "account_name": _("Total {0} ({1})").format(_(root_type), _(balance_must_be)),
        "account": _("Total {0} ({1})").format(_(root_type), _(balance_must_be)),
        "currency": company_currency,
        "opening_balance": 0.0,
    }

    for row in out:
        if not row.get("parent_account"):
            for period in period_list:
                total_row.setdefault(period.key, 0.0)
                total_row[period.key] += row.get(period.key, 0.0)

            total_row.setdefault("total", 0.0)
            total_row["total"] += flt(row["total"])
            total_row["opening_balance"] += row["opening_balance"]

    if "total" in total_row:
        out.append(total_row)

        # Append a blank row after Total for spacing
        out.append({})
