from datetime import datetime

from odoo import models, fields, api, exceptions
from odoo.exceptions import UserError, ValidationError
import re
import logging
from odoo.tools.float_utils import float_round
from odoo.tools.float_utils import float_compare


_logger = logging.getLogger(__name__)


class TransactionBooking(models.Model):
    _name = "idil.transaction_booking"
    _description = "Transaction Booking"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    # Primary Key Fields
    transaction_number = fields.Integer(string="Transaction Number")
    reffno = fields.Char(string="Reference Number")  # Consider renaming for clarity
    journal_entry_id = fields.Many2one("idil.journal.entry", string="Journal Entry")

    vendor_id = fields.Many2one("idil.vendor.registration", string="Vendor")
    customer_id = fields.Many2one("idil.customer.registration", string="Customer")
    vendor_phone = fields.Char(
        related="vendor_id.phone", string="Vendor Phone", readonly=True
    )
    vendor_email = fields.Char(
        related="vendor_id.email", string="Vendor Email", readonly=True
    )

    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Sales Person"
    )
    # Add a field to link to the SaleOrder. This assumes you have a unique identifier (like an ID) for SaleOrder.

    sale_order_id = fields.Many2one(
        "idil.sale.order",
        string="Sales Order",
        index=True,
        ondelete="cascade",
    )
    cusotmer_sale_order_id = fields.Many2one(
        "idil.customer.sale.order",
        string="Linked Customer Sale Order",
        ondelete="cascade",
    )

    order_number = fields.Char(string="Order Number")
    Sales_order_number = fields.Char(string="Sales Order Number")

    payment_method = fields.Selection(
        [
            ("cash", "Cash"),
            ("ap", "A/P"),
            ("bank_transfer", "Bank Transfer"),
            ("other", "Other"),
            ("internal", "Internal"),
            ("receivable", "A/R"),
            ("opening_balance", "Opening Balance"),
            ("pos", "POS"),
            ("bulk_payment", "Bulk Payment"),
            ("commission_payment", "Commission Payment"),
        ],
        string="Payment Method",
    )

    pos_payment_method = fields.Many2one(
        "pos.payment.method", string="POS Payment Method"
    )

    payment_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("paid", "Paid"),
            ("partial_paid", "Partial Paid"),
            ("posted", "Posted"),
        ],
        string="Payment Status",
        help="Description or additional information about the payment status.",
    )

    trx_date = fields.Date(
        string="Transaction Date", default=lambda self: fields.Date.today()
    )
    # amount = fields.Float(string='Amount')
    trx_source_id = fields.Many2one(
        "idil.transaction.source",
        string="Transaction Source",
        help="Select the transaction source.",
    )
    amount = fields.Float(string="Amount", store=True, digits=(16, 5))
    amount_paid = fields.Float(string="Amount Paid", digits=(16, 5))
    remaining_amount = fields.Float(string="Remaining Amount", store=True)

    debit_total = fields.Float(
        string="Total Debit",
        compute="_compute_debit_credit_total",
        store=True,
        digits=(16, 5),
    )
    credit_total = fields.Float(
        string="Total Credit",
        compute="_compute_debit_credit_total",
        store=True,
        digits=(16, 5),
    )

    booking_lines = fields.One2many(
        "idil.transaction_bookingline",
        "transaction_booking_id",
        string="Transaction Lines",
    )

    # Add a Many2one field to select a cash account
    cash_account_id = fields.Many2one(
        "idil.chart.account",
        string="Cash Account",
        domain=[("account_type", "=", "cash")],
        help="Select the cash account for transactions.",
    )
    vendor_transactions = fields.One2many(
        "idil.vendor_transaction",
        "transaction_booking_id",
        string="Vendor Transactions",
        ondelete="cascade",
    )

    # Add a Many2one field to link to PurchaseOrder
    purchase_order_id = fields.Many2one(
        "idil.purchase_order", string="Linked Purchase Order", ondelete="cascade"
    )
    # Link to Sales Payment
    sales_payment_id = fields.Many2one(
        "idil.sales.payment",
        string="Sales Payment",
        ondelete="cascade",
        help="The sales payment this transaction booking is associated with.",
    )
    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        string="Manufacturing Order",
        tracking=True,
        ondelete="cascade",  # Add this to enable automatic deletion
    )
    sale_return_id = fields.Many2one(
        "idil.sale.return",
        string="Sales Return",
        ondelete="cascade",
    )
    product_purchase_order_id = fields.Many2one(
        "idil.product.purchase.order",
        string="Product Purchase Order",
        ondelete="cascade",
    )
    adjustment_id = fields.Many2one(
        "idil.product.adjustment",
        string="Adjustment Reference",
        ondelete="cascade",  # 🔁 Cascade delete
        index=True,
    )
    item_opening_balance_id = fields.Many2one(
        "idil.item.opening.balance",
        string="Item Opening Balance",
        ondelete="cascade",  # ✅ auto-delete booking when opening balance is deleted
        index=True,
    )
    return_id = fields.Many2one(
        "idil.purchase_return",
        string="Purchase Return",
        ondelete="cascade",
    )
    product_return_id = fields.Many2one(
        "idil.product.purchase_return",
        string="Purchase Return",
        ondelete="cascade",
    )
    bulk_payment_id = fields.Many2one(
        "idil.vendor.bulk.payment", string="Related Bulk Payment", ondelete="cascade"
    )
    sales_opening_balance_id = fields.Many2one(
        "idil.sales.opening.balance",
        string="Opening Balance",
        ondelete="cascade",
    )
    customer_opening_balance_id = fields.Many2one(
        "idil.customer.opening.balance.line",
        string="Opening Balance",
        ondelete="cascade",
    )
    vendor_opening_balance_id = fields.Many2one(
        "idil.vendor.opening.balance.line",
        string="Vendor Opening Balance",
        ondelete="cascade",
    )
    customer_sales_return_id = fields.Many2one(
        "idil.customer.sale.return.line",
        string="Customer Sales Return",
        ondelete="cascade",
    )
    currency_exchange_id = fields.Many2one(
        "idil.currency.exchange", string="Currency Exchange", ondelete="cascade"
    )
    product_opening_balance_id = fields.Many2one(
        "my_product.opening.balance",
        string="Product Opening Balance",
        ondelete="cascade",  # ✅ auto-delete booking when opening balance is deleted
        index=True,
    )

    employee_id = fields.Many2one("idil.employee", string="Employee", tracking=True)
    staff_sales_id = fields.Many2one(
        "idil.staff.sales", string="Staff Sales", help="Linked staff sales transaction"
    )
    employee_salary_advance_id = fields.Many2one(
        "idil.employee.salary.advance", string="Advance Ref"
    )
    employee_salary_id = fields.Many2one(
        "idil.employee.salary",
        string="Employee Salary Reference",
        ondelete="set null",
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        store=True,
        readonly=True,
    )

    rate = fields.Float(
        string="Exchange Rate",
        digits=(16, 5),
        store=True,
        readonly=True,
        required=True,
        help="Select the exchange rate for the transaction.",
        tracking=True,
    )

    @api.constrains("trx_date")
    def _check_trx_date_not_future(self):
        for rec in self:
            if rec.trx_date and rec.trx_date > fields.Date.today():
                raise ValidationError("Transaction Date cannot be in the future.")

    @api.constrains("amount_paid")
    def _check_amount_paid(self):
        if self.env.context.get("skip_validations"):
            return

        precision = self.env["decimal.precision"].precision_get("Account")

        for record in self:
            if (
                float_compare(
                    record.amount_paid, record.amount, precision_digits=precision
                )
                > 0
            ):
                raise ValidationError(
                    "The paid amount cannot be greater than the balance.\nBalance: %s\nAmount Needed to Pay: %s"
                    % (record.amount, record.amount_paid)
                )

    @api.onchange("amount_paid")
    def _onchange_amount_paid(self):
        if self.env.context.get("skip_validations"):
            return
        if self.amount_paid > self.amount:
            raise ValidationError(
                "The paid amount cannot be greater than the balance.\nBalance: %s\nAmount Needed to Pay: %s"
                % (self.amount, self.amount_paid)
            )

    def action_pay(self):
        try:
            with self.env.cr.savepoint():
                for record in self:
                    if not record.cash_account_id:
                        raise ValidationError("Select Cash account")
                    if record.amount_paid > record.amount:
                        raise ValidationError(
                            "The payment amount cannot exceed the current balance."
                        )

                    # Create two transaction booking lines or update
                    cr_account = record.sales_person_id.account_receivable_id.id
                    dr_account = record.cash_account_id.id
                    if cr_account and dr_account:
                        # Find existing transaction booking lines

                        existing_lines = self.env[
                            "idil.transaction_bookingline"
                        ].search(
                            [
                                ("transaction_booking_id", "=", record.id),
                                (
                                    "transaction_booking_id.payment_status",
                                    "!=",
                                    "pending",
                                ),
                            ]
                        )
                        # Update existing lines or create them if they don't exist
                        for line in existing_lines:
                            if line.description == "Receipt":
                                if line.transaction_type == "cr":
                                    line.cr_amount = record.amount_paid
                                elif line.transaction_type == "dr":
                                    line.dr_amount = record.amount_paid

                        if not existing_lines:
                            # Create credit transaction booking line
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": record.id,
                                    "description": "Receipt",
                                    "transaction_type": "cr",
                                    "cr_amount": record.amount_paid,
                                    "dr_amount": 0,
                                    "account_number": cr_account,
                                }
                            )

                            # Create debit transaction booking line
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": record.id,
                                    "description": "Receipt",
                                    "transaction_type": "dr",
                                    "cr_amount": 0,
                                    "dr_amount": record.amount_paid,
                                    "account_number": dr_account,
                                }
                            )

                        update_vals = {
                            "trx_source_id": 3,  # New trx_source_id value
                        }

                        # Update payment status based on remaining amount
                        if record.remaining_amount == 0:
                            record.payment_status = "paid"
                        else:
                            record.payment_status = "partial_paid"

                        record.amount_paid = record.amount_paid
                        record.remaining_amount = record.remaining_amount
                        # Write the changes to the database
                        record.write(update_vals)
                    else:
                        # Log an error or handle the case where accounts are not properly set
                        _logger.error(
                            f"Accounts not properly set for transaction booking {record.id}."
                        )
        except Exception as e:
            _logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    @api.depends("booking_lines.dr_amount", "booking_lines.cr_amount")
    def _compute_debit_credit_total(self):
        for record in self:
            record.debit_total = sum(line.dr_amount for line in record.booking_lines)
            record.credit_total = sum(line.cr_amount for line in record.booking_lines)

    @api.model
    def create(self, vals):
        # vals['reffno'] = self._generate_booking_reference(vals)
        vals["transaction_number"] = self._get_next_transaction_number()

        transaction_record = super(TransactionBooking, self).create(vals)

        return transaction_record

    def _get_next_transaction_number(self):
        max_transaction_number = (
            self.env["idil.transaction_booking"]
            .search([], order="transaction_number desc", limit=1)
            .transaction_number
            or 0
        )
        return max_transaction_number + 1

    def action_add_default_lines(self):
        for record in self:
            # Add a debit line
            self.env["idil.transaction_bookingline"].create(
                {
                    "transaction_booking_id": record.id,
                    "transaction_type": "dr",
                    "dr_amount": 0.0,  # Default amount; adjust as necessary
                    "cr_amount": 0.0,  # Ensured to be zero for debit line
                    "description": "Default debit line",
                }
            )
            # Add a credit line
            self.env["idil.transaction_bookingline"].create(
                {
                    "transaction_booking_id": record.id,
                    "transaction_type": "cr",
                    "dr_amount": 0.0,  # Ensured to be zero for credit line
                    "cr_amount": 0.0,  # Default amount; adjust as necessary
                    "description": "Default credit line",
                }
            )

    def update_related_booking_lines(self):
        for line in self.booking_lines:
            if line.transaction_type == "dr":
                line.dr_amount = (
                    self.amount
                )  # Update dr_amount to total sale order amount for debit lines
                line.cr_amount = 0
            elif line.transaction_type == "cr":
                line.cr_amount = (
                    self.amount
                )  # Update cr_amount to total sale order amount for credit lines
                line.dr_amount = 0


class TransactionBookingline(models.Model):
    _name = "idil.transaction_bookingline"
    _description = "Transaction Booking Line"
    _order = "id desc"

    # Secondary Key Fields
    transaction_booking_id = fields.Many2one(
        "idil.transaction_booking", string="Transaction Booking", ondelete="cascade"
    )

    # order_line = fields.Char(string='Order Line')
    sl_line = fields.Integer(string="Order Line")
    order_line = fields.Many2one("idil.purchase_order.line", ondelete="cascade")

    description = fields.Char(string="Description")
    item_id = fields.Many2one("idil.item", string="Item")
    product_id = fields.Many2one("my_product.product", string="Product")

    account_number = fields.Many2one(
        "idil.chart.account", string="Account Number", required=True
    )
    account_display = fields.Char(
        string="Account Display", compute="_compute_account_display", store=True
    )

    transaction_type = fields.Selection(
        [("dr", "Debit"), ("cr", "Credit")], string="Transaction Type", required=True
    )
    dr_amount = fields.Float(string="Debit Amount", digits=(16, 5))
    cr_amount = fields.Float(string="Credit Amount", digits=(16, 5))
    transaction_date = fields.Date(
        string="Transaction Date", default=lambda self: fields.Date.today()
    )
    vendor_payment_id = fields.Many2one(
        "idil.vendor_payment", string="Vendor Payment", ondelete="cascade"
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="account_number.currency_id",
        store=True,
        readonly=True,
    )

    commission_payment_id = fields.Many2one(
        "idil.commission.payment", string="Commission Payment", ondelete="cascade"
    )

    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    sale_order_id = fields.Many2one(
        "idil.sale.order",
        string="Sales Order",
        index=True,
        ondelete="cascade",
    )
    sales_payment_id = fields.Many2one(
        "idil.sales.payment",
        string="Sales Payment",
        ondelete="cascade",
        help="The sales payment this transaction booking line is associated with.",
    )

    sale_return_id = fields.Many2one(
        "idil.sale.return",
        string="Sales Return",
        ondelete="cascade",
    )
    product_purchase_order_id = fields.Many2one(
        "idil.product.purchase.order",
        string="Product Purchase Order",
        ondelete="cascade",
    )
    adjustment_id = fields.Many2one(
        "idil.product.adjustment",
        string="Adjustment Reference",
        ondelete="cascade",  # 🔁 Cascade delete
        index=True,
    )
    item_opening_balance_id = fields.Many2one(
        "idil.item.opening.balance",
        string="Item Opening Balance",
        ondelete="cascade",  # ✅ auto-delete booking when opening balance is deleted
        index=True,
    )
    return_id = fields.Many2one(
        "idil.purchase_return",
        string="Purchase Return",
        ondelete="cascade",
    )
    vendor_bulk_payment_id = fields.Many2one(
        "idil.vendor.bulk.payment",
        string="Vendor Bulk Payment",
        ondelete="cascade",  # Ensures deletion of vendor payments when bulk is deleted
    )
    bulk_payment_line_id = fields.Many2one(
        "idil.commission.bulk.payment.line",
        string="Bulk Payment Line",
        readonly=True,
    )

    sales_opening_balance_id = fields.Many2one(
        "idil.sales.opening.balance", string="Opening Balance", ondelete="cascade"
    )

    customer_opening_balance_id = fields.Many2one(
        "idil.customer.opening.balance.line",
        string="Customer Opening Balance",
        ondelete="cascade",
    )
    vendor_opening_balance_id = fields.Many2one(
        "idil.vendor.opening.balance.line",
        string="Vendor Opening Balance",
        ondelete="cascade",
    )
    customer_sales_return_id = fields.Many2one(
        "idil.customer.sale.return.line",
        string="Customer Sales Return",
        ondelete="cascade",
    )
    product_return_id = fields.Many2one(
        "idil.product.purchase_return",
        string="Purchase Return",
        ondelete="cascade",
    )
    product_opening_balance_id = fields.Many2one(
        "my_product.opening.balance",
        string="Product Opening Balance",
        ondelete="cascade",  # ✅ auto-delete booking when opening balance is deleted
        index=True,
    )

    employee_id = fields.Many2one("idil.employee", string="Employee", tracking=True)
    staff_sales_id = fields.Many2one(
        "idil.staff.sales", string="Staff Sales", help="Linked staff sales transaction"
    )
    employee_salary_advance_id = fields.Many2one(
        "idil.employee.salary.advance", string="Advance Ref"
    )
    employee_salary_id = fields.Many2one(
        "idil.employee.salary",
        string="Employee Salary Reference",
        ondelete="set null",
    )
    rate = fields.Float(
        string="Exchange Rate",
        related="transaction_booking_id.rate",
        store=True,
        readonly=True,
        help="Same rate as on the parent booking.",
    )

    @api.constrains("transaction_date")
    def _check_transaction_date_not_future(self):
        for rec in self:
            if rec.transaction_date and rec.transaction_date > fields.Date.today():
                raise ValidationError("Transaction Line Date cannot be in the future.")

    @api.depends("account_number")
    def _compute_account_display(self):
        for line in self:
            if line.account_number:
                line.account_display = (
                    f"{line.account_number.code} - {line.account_number.name} "
                    f"- {line.account_number.currency_id.name}"
                )
            else:
                line.account_display = ""

    @api.model
    def compute_trial_balance(self, report_currency_id):
        self.env.cr.execute(
            """
                SELECT
                    tb.account_number,
                    ca.currency_id,
                    SUM(tb.dr_amount) AS dr_total,
                    SUM(tb.cr_amount) AS cr_total
                FROM
                    idil_transaction_bookingline tb
                JOIN idil_chart_account ca ON tb.account_number = ca.id
                JOIN idil_chart_account_subheader cb ON ca.subheader_id = cb.id
                JOIN idil_chart_account_header ch ON cb.header_id = ch.id
                WHERE
                    ca.currency_id = %s  -- Filter by selected report currency
                GROUP BY
                    tb.account_number, ca.currency_id, ch.code
                HAVING
                    SUM(tb.dr_amount) - SUM(tb.cr_amount) <> 0
                ORDER BY
                    ch.code
            """,
            (report_currency_id.id,),
        )
        result = self.env.cr.dictfetchall()

        total_dr_balance = 0
        total_cr_balance = 0

        # Clear previous trial balance records
        self.env["idil.trial.balance"].search([]).unlink()

        for line in result:
            account = self.env["idil.chart.account"].browse(line["account_number"])
            # Compute the net balance for the account
            net_balance = line["dr_total"] - line["cr_total"]

            if net_balance > 0:
                # Positive net balance indicates a debit balance
                dr_balance = net_balance
                cr_balance = 0
                total_dr_balance += dr_balance
            else:
                # Negative net balance indicates a credit balance
                dr_balance = 0
                cr_balance = abs(net_balance)
                total_cr_balance += cr_balance

            # Create the trial balance record
            self.env["idil.trial.balance"].create(
                {
                    "account_number": account.id,
                    "header_name": account.header_name,
                    "currency_id": line["currency_id"],
                    "dr_balance": dr_balance,
                    "cr_balance": cr_balance,
                }
            )

        # Add a grand total row if a report currency is specified
        if report_currency_id:
            self.env["idil.trial.balance"].create(
                {
                    "account_number": None,
                    "currency_id": report_currency_id.id,
                    "dr_balance": total_dr_balance,
                    "cr_balance": total_cr_balance,
                    "label": "Grand Total",
                }
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Trial Balance",
            "view_mode": "tree",
            "res_model": "idil.trial.balance",
            "target": "new",
        }

    def compute_company_trial_balance(
        self, report_currency_id, company_id, as_of_date, exact_day=False
    ):
        # --- normalize to a pure date (no timezone issues) ---
        as_of_date = fields.Date.to_date(as_of_date)

        Currency = self.env["res.currency"]
        Account = self.env["idil.chart.account"]
        TrialBal = self.env["idil.company.trial.balance"]

        # Use the report currency if provided, else company currency
        report_currency = report_currency_id or company_id.currency_id

        # --- clear only my previous rows (and this company if field exists) ---
        clear_domain = [("create_uid", "=", self.env.uid)]
        if "company_id" in TrialBal._fields:
            clear_domain.append(("company_id", "=", company_id.id))
        TrialBal.search(clear_domain).unlink()

        # --- fetch raw lines using ONLY transaction_date ---
        comparator = "=" if exact_day else "<="
        self.env.cr.execute(
            f"""
            SELECT
                tb.account_number,
                tb.dr_amount,
                tb.cr_amount,
                tb.transaction_date::date AS tdate,
                ca.currency_id
            FROM idil_transaction_bookingline tb
            JOIN idil_chart_account ca ON tb.account_number = ca.id
            WHERE tb.company_id = %s
            AND tb.transaction_date {comparator} %s::date
            AND ca.name != 'Exchange Clearing Account'
        """,
            (company_id.id, as_of_date),
        )
        rows = self.env.cr.dictfetchall()

        # --- aggregate in report currency, converting at tdate (transaction_date) ---
        balances = {}  # {account_id: {'dr': x, 'cr': y}}
        for r in rows:
            acc_id = r["account_number"]
            tdate = r["tdate"]
            src_cur = Currency.browse(r["currency_id"])
            dr_src = r["dr_amount"] or 0.0
            cr_src = r["cr_amount"] or 0.0

            dr_rep = src_cur._convert(
                dr_src, report_currency, company_id, tdate, round=False
            )
            cr_rep = src_cur._convert(
                cr_src, report_currency, company_id, tdate, round=False
            )

            b = balances.setdefault(acc_id, {"dr": 0.0, "cr": 0.0})
            b["dr"] += dr_rep
            b["cr"] += cr_rep

        # --- write detail lines + grand total ---
        grand_dr = grand_cr = 0.0
        for acc_id, t in balances.items():
            net = t["dr"] - t["cr"]
            if abs(net) < 1e-9:
                continue  # skip zero-net

            dr_bal = report_currency.round(net if net > 0 else 0.0)
            cr_bal = report_currency.round(-net if net < 0 else 0.0)

            acc = Account.browse(acc_id)
            vals = {
                "account_number": acc.id,
                "header_name": acc.header_name,
                "currency_id": report_currency.id,
                "dr_balance": dr_bal,
                "cr_balance": cr_bal,
            }
            if "company_id" in TrialBal._fields:
                vals["company_id"] = company_id.id
            if "as_of_date" in TrialBal._fields:
                vals["as_of_date"] = as_of_date
            TrialBal.create(vals)

            grand_dr += dr_bal
            grand_cr += cr_bal

        total_vals = {
            "account_number": False,
            "currency_id": report_currency.id,
            "label": (
                f"Grand Total (as of {as_of_date})"
                if not exact_day
                else f"Grand Total ({as_of_date})"
            ),
            "dr_balance": grand_dr,
            "cr_balance": grand_cr,
        }
        if "company_id" in TrialBal._fields:
            total_vals["company_id"] = company_id.id
        if "as_of_date" in TrialBal._fields:
            total_vals["as_of_date"] = as_of_date
        TrialBal.create(total_vals)

        return {
            "type": "ir.actions.act_window",
            "name": f"Company Trial Balance — {as_of_date}",
            "view_mode": "tree",
            "res_model": "idil.company.trial.balance",
            "domain": clear_domain,  # show only the rows we just created
            "target": "new",
        }

    def compute_income_statement(self, company_id):
        # Retrieve USD currency
        usd_currency = self.env["res.currency"].search([("name", "=", "USD")], limit=1)

        # Clear previous report data
        self.env["idil.income.statement.report"].search([]).unlink()

        # Define account types for expenses and profits based on the starting code
        expense_accounts = self.env["idil.chart.account"].search(
            [("code", "=like", "5%")]
        )
        profit_accounts = self.env["idil.chart.account"].search(
            [("code", "=like", "4%")]
        )

        total_expenses = 0
        total_income = 0

        # Compute total expenses
        for account in expense_accounts:
            self.env.cr.execute(
                """
                SELECT
                    SUM(tb.dr_amount) - SUM(tb.cr_amount) AS total
                FROM
                    idil_transaction_bookingline tb
                WHERE
                    tb.company_id = %s AND tb.account_number = %s
                GROUP BY
                    tb.account_number
                HAVING
                    SUM(tb.dr_amount) - SUM(tb.cr_amount) != 0
                """,
                (company_id.id, account.id),
            )

            result = self.env.cr.fetchone()
            amount = result[0] if result else 0

            # Convert amount to USD if necessary
            if account.currency_id.id != usd_currency.id:
                amount = account.currency_id._convert(
                    amount, usd_currency, self.env.user.company_id, fields.Date.today()
                )

            # Only create a report entry if the amount is non-zero
            if amount != 0:
                # Accumulate total expenses
                total_expenses += amount

                # Create report entry for each expense account
                self.env["idil.income.statement.report"].create(
                    {
                        "account_number": account.id,
                        "amount": amount,
                        "currency_id": usd_currency.id,
                    }
                )

        # Add subtotal for expenses only if there are any
        if total_expenses != 0:
            self.env["idil.income.statement.report"].create(
                {
                    "account_number": None,
                    "account_type": "Expense Subtotal",
                    "amount": total_expenses,
                    "currency_id": usd_currency.id,
                }
            )

        # Compute total income
        for account in profit_accounts:
            self.env.cr.execute(
                """
                SELECT
                    SUM(tb.cr_amount) - SUM(tb.dr_amount) AS total
                FROM
                    idil_transaction_bookingline tb
                WHERE
                    tb.company_id = %s AND tb.account_number = %s
                GROUP BY
                    tb.account_number
                HAVING
                    SUM(tb.cr_amount) - SUM(tb.dr_amount) != 0
                """,
                (company_id.id, account.id),
            )

            result = self.env.cr.fetchone()
            amount = result[0] if result else 0

            # Convert amount to USD if necessary
            if account.currency_id.id != usd_currency.id:
                amount = account.currency_id._convert(
                    amount, usd_currency, self.env.user.company_id, fields.Date.today()
                )

            # Only create a report entry if the amount is non-zero
            if amount != 0:
                # Accumulate total income
                total_income += amount

                # Create report entry for each profit account
                self.env["idil.income.statement.report"].create(
                    {
                        "account_number": account.id,
                        "amount": amount,
                        "currency_id": usd_currency.id,
                    }
                )

        # Add subtotal for income only if there are any
        if total_income != 0:
            self.env["idil.income.statement.report"].create(
                {
                    "account_number": None,
                    "account_type": "Income Subtotal",
                    "amount": total_income,
                    "currency_id": usd_currency.id,
                }
            )

        # Calculate and add gross profit
        gross_profit = total_income - total_expenses
        self.env["idil.income.statement.report"].create(
            {
                "account_number": None,
                "account_type": "Gross Profit",
                "amount": gross_profit,
                "currency_id": usd_currency.id,
            }
        )

        return {
            "type": "ir.actions.act_window",
            "name": "Income Statement",
            "view_mode": "tree",
            "res_model": "idil.income.statement.report",
            "target": "new",
        }


class IncomeStatementReport(models.TransientModel):
    _name = "idil.income.statement.report"
    _description = "Income Statement Report"

    account_number = fields.Many2one("idil.chart.account", string="Account Number")
    account_type = fields.Char(string="Description")
    amount = fields.Float(string="Amount")
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    label = fields.Char(string="Label")


class IncomeStatementWizard(models.TransientModel):
    _name = "idil.income.statement.wizard"
    _description = "Income Statement Wizard"

    company_id = fields.Many2one("res.company", string="Company", required=True)

    def action_compute_income_statement(self):
        self.ensure_one()
        action = self.env["idil.transaction_bookingline"].compute_income_statement(
            self.company_id
        )
        return action


class CompanyTrialBalance(models.Model):
    _name = "idil.company.trial.balance"
    _description = "Company Trial Balance"

    account_number = fields.Many2one("idil.chart.account", string="Account Number")
    header_name = fields.Char(string="Account Type")
    dr_balance = fields.Float(string="Dr", digits=(16, 3))
    cr_balance = fields.Float(string="Cr", digits=(16, 3))
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)
    label = fields.Char(string="Label", compute="_compute_label")
    company_id = fields.Many2one("res.company", string="Company", readonly=True)

    @api.depends("account_number", "dr_balance", "cr_balance")
    def _compute_label(self):
        for record in self:
            if not record.account_number:
                record.label = "Grand Total"
            else:
                record.label = ""


class CompanyTrialBalanceWizard(models.TransientModel):
    _name = "idil.company.trial.balance.wizard"
    _description = "Company Trial Balance Wizard"

    company_id = fields.Many2one("res.company", string="Company", required=True)
    as_of_date = fields.Date(string="As of Date", required=True)

    def action_compute_company_trial_balance(self):
        self.ensure_one()
        usd_currency = self.env["res.currency"].search([("name", "=", "USD")], limit=1)
        action = self.env["idil.transaction_bookingline"].compute_company_trial_balance(
            usd_currency, self.company_id, self.as_of_date
        )
        action["context"] = {
            "default_name": f"Company Trial Balance for {self.company_id.name} as of {self.as_of_date}"
        }

        return action
