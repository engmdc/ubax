from odoo import models, fields, api, exceptions
from datetime import datetime
from datetime import date
import re
from odoo.exceptions import ValidationError, UserError
import logging

from odoo.tools import float_round, format_datetime

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _name = "idil.sale.order"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Sale Order"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )
    name = fields.Char(string="Sales Reference", tracking=True)

    sales_person_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True
    )
    # Add a reference to the salesperson's order
    salesperson_order_id = fields.Many2one(
        "idil.salesperson.place.order",
        string="Related Salesperson Order",
        help="This field links to the salesperson order that this actual order is based on.",
    )

    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now)
    order_lines = fields.One2many(
        "idil.sale.order.line",
        "order_id",
        string="Order Lines",
        tracking=True,
    )
    order_total = fields.Float(
        string="Order Total",
        compute="_compute_order_total",
        store=True,
        tracking=True,
    )

    # 1) default state: DRAFT (not confirmed)
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancel", "Cancelled")],
        default="draft",
        tracking=True,
    )

    commission_amount = fields.Float(
        string="Commission Amount",
        compute="_compute_total_commission",
        store=True,
        tracking=True,
    )
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env["res.currency"].search(
            [("name", "=", "SL")], limit=1
        ),
        readonly=True,
        tracking=True,
    )
    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
        tracking=True,
    )
    total_due_usd = fields.Float(
        string="Total Due (USD)",
        compute="_compute_totals_in_usd",
        store=True,
        tracking=True,
    )
    total_commission_usd = fields.Float(
        string="Commission (USD)",
        compute="_compute_totals_in_usd",
        store=True,
        tracking=True,
    )
    total_discount_usd = fields.Float(
        string="Discount (USD)",
        compute="_compute_totals_in_usd",
        store=True,
        tracking=True,
    )
    total_returned_qty = fields.Float(
        string="Total Returned Quantity",
        compute="_compute_total_returned_qty",
        store=False,
        readonly=True,
    )
    total_cost_price = fields.Float(
        string="Total Cost Price",
        compute="_compute_total_cost_price",
        store=False,
        digits=(16, 6),
        readonly=True,
        tracking=True,
    )

    @api.depends("order_lines", "order_lines.product_id", "order_lines.quantity")
    def _compute_total_cost_price(self):
        for order in self:
            total = 0.0
            for line in order.order_lines:
                product = line.product_id
                qty = line.quantity
                if product and qty:
                    # 1. If product has a BOM
                    if product.bom_id:
                        bom_currency = product.bom_id.currency_id.name
                        if bom_currency == "SL":
                            total += (product.cost * qty) / order.rate
                        else:
                            total += product.cost * qty
                    else:
                        # 2. If no BOM, assume cost is SL and convert
                        total += (product.cost * qty) / order.rate
            order.total_cost_price = total

    @api.depends("order_lines", "order_lines.product_id")
    def _compute_total_returned_qty(self):
        for order in self:
            return_lines = self.env["idil.sale.return.line"].search(
                [
                    ("return_id.sale_order_id", "=", order.id),
                    ("return_id.state", "=", "confirmed"),
                ]
            )
            order.total_returned_qty = sum(return_lines.mapped("returned_quantity"))

    @api.depends(
        "order_lines.subtotal",
        "order_lines.commission_amount",
        "order_lines.discount_amount",
        "rate",
    )
    def _compute_totals_in_usd(self):
        for order in self:
            subtotal = sum(order.order_lines.mapped("subtotal"))
            commission = sum(order.order_lines.mapped("commission_amount"))
            discount = sum(order.order_lines.mapped("discount_amount"))

            rate = order.rate or 0.0
            order.total_due_usd = subtotal / rate if rate else 0.0
            order.total_commission_usd = commission / rate if rate else 0.0
            order.total_discount_usd = discount / rate if rate else 0.0

    @api.depends("currency_id", "order_date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.order_date)
                if order.order_date
                else fields.Date.today()
            )

            rate_rec = Rate.search(
                [
                    ("currency_id", "=", order.currency_id.id),
                    ("name", "<=", doc_date),
                    ("company_id", "in", [order.company_id.id, False]),
                ],
                order="company_id desc, name desc",
                limit=1,
            )

            order.rate = rate_rec.rate or 0.0

    @api.depends("order_lines.quantity", "order_lines.product_id.commission")
    def _compute_total_commission(self):
        for order in self:
            total_commission = 0.0
            for line in order.order_lines:
                product = line.product_id
                if product.is_sales_commissionable:
                    if not product.sales_account_id:
                        raise ValidationError(
                            (
                                "Product '%s' does not have a Sales Commission Account set."
                            )
                            % product.name
                        )
                    if product.commission <= 0:
                        raise ValidationError(
                            ("Product '%s' does not have a valid Commission Rate set.")
                            % product.name
                        )
                    total_commission += line.commission_amount
            order.commission_amount = total_commission

    def _generate_order_reference(self, vals):
        bom_id = vals.get("bom_id", False)
        if bom_id:
            bom = self.env["idil.bom"].browse(bom_id)
            bom_name = (
                re.sub("[^A-Za-z0-9]+", "", bom.name[:2]).upper()
                if bom and bom.name
                else "XX"
            )
            date_str = "/" + py_datetime.now().strftime("%d%m%Y")
            day_night = "/DAY/" if py_datetime.now().hour < 12 else "/NIGHT/"
            sequence = self.env["ir.sequence"].next_by_code("idil.sale.order.sequence")
            sequence = sequence[-3:] if sequence else "000"
            return f"{bom_name}{date_str}{day_night}{sequence}"
        else:
            return self.env["ir.sequence"].next_by_code("idil.sale.order.sequence")

    @api.depends("order_lines.subtotal")
    def _compute_order_total(self):
        for order in self:
            order.order_total = sum(order.order_lines.mapped("subtotal"))

    @api.onchange("sales_person_id")
    def _onchange_sales_person_id(self):
        if not self.sales_person_id:
            return

        last_order = self.env["idil.salesperson.place.order"].search(
            [("salesperson_id", "=", self.sales_person_id.id), ("state", "=", "draft")],
            order="order_date desc",
            limit=1,
        )

        if last_order:
            order_lines_cmds = [(5, 0, 0)]
            for line in last_order.order_lines:
                discount_quantity = (
                    (line.product_id.discount / 100) * (line.quantity)
                    if line.product_id.is_quantity_discount
                    else 0.0
                )
                order_lines_cmds.append(
                    (
                        0,
                        0,
                        {
                            "product_id": line.product_id.id,
                            "quantity_Demand": line.quantity,
                            "discount_quantity": discount_quantity,
                            "quantity": line.quantity,
                        },
                    )
                )
            self.order_lines = order_lines_cmds
        else:
            raise UserError(
                ("This salesperson does not have any draft orders to reference.")
            )

    # 2) CREATE: link salesperson draft order & set reference — but DO NOT post any side-effects
    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                if "sales_person_id" in vals:
                    salesperson_id = vals["sales_person_id"]
                    sp_order = self.env["idil.salesperson.place.order"].search(
                        [
                            ("salesperson_id", "=", salesperson_id),
                            ("state", "=", "draft"),
                        ],
                        order="order_date desc",
                        limit=1,
                    )
                    if sp_order:
                        vals["salesperson_order_id"] = sp_order.id
                    else:
                        raise UserError(
                            (
                                "No draft Salesperson Order found for the given salesperson."
                            )
                        )

                if not vals.get("name"):
                    vals["name"] = self._generate_order_reference(vals)

                vals["state"] = "draft"

                new_order = super().create(vals)
                return new_order
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    # 3) CONFIRM: single place to do validations + posting (receipt, movements, accounting)
    def button_confirm(self):
        for order in self:
            if order.state == "confirmed":
                continue

            order.precheck_before_confirm()
            order.freeze_exchange_rate()

            try:
                with self.env.cr.savepoint():
                    # post everything
                    order.post_salesperson_transactions_on_confirm()
                    order.create_receipt_on_confirm()
                    order.create_movements_on_confirm()
                    order.book_accounting_entry()

                    # flip states only after successful postings
                    order.state = "confirmed"
                    if order.salesperson_order_id:
                        order.salesperson_order_id.write({"state": "confirmed"})

                    _logger.info("Confirmed: %s", order.name)

            except Exception as e:
                _logger.error("Confirm failed for %s: %s", order.name, e)
                raise ValidationError("Confirm failed: %s" % e)

    # ---- helpers -------------------------------------------------------------
    def post_salesperson_transactions_on_confirm(self):
        """Post salesperson transactions for each line (moved from SaleOrderLine.create)."""
        self.ensure_one()
        if not self.sales_person_id:
            return
        for line in self.order_lines:
            # Total sales amount (your existing formula)
            self.env["idil.salesperson.transaction"].create(
                {
                    "sales_person_id": self.sales_person_id.id,
                    "sale_order_id": self.id,
                    "date": self.order_date,
                    "order_id": self.id,
                    "transaction_type": "out",
                    "amount": line.subtotal
                    + line.discount_amount
                    + line.commission_amount,
                    "description": (
                        f"Sales Amount of - Order Line for {line.product_id.name} "
                        f"(Qty: {line.quantity})"
                    ),
                }
            )
            # Commission (negative out)
            self.env["idil.salesperson.transaction"].create(
                {
                    "sales_person_id": self.sales_person_id.id,
                    "sale_order_id": self.id,
                    "date": self.order_date,
                    "order_id": self.id,
                    "transaction_type": "out",
                    "amount": line.commission_amount * -1,
                    "description": (
                        f"Sales Commission Amount of - Order Line for  "
                        f"{line.product_id.name} (Qty: {line.quantity})"
                    ),
                }
            )
            # Discount (negative out)
            self.env["idil.salesperson.transaction"].create(
                {
                    "sales_person_id": self.sales_person_id.id,
                    "sale_order_id": self.id,
                    "date": self.order_date,
                    "order_id": self.id,
                    "transaction_type": "out",
                    "amount": line.discount_amount * -1,
                    "description": (
                        f"Sales Discount Amount of - Order Line for  "
                        f"{line.product_id.name} (Qty: {line.quantity})"
                    ),
                }
            )

    def precheck_before_confirm(self):
        self.ensure_one()

        if not self.order_lines:
            raise UserError(("You must add at least one order line."))

        if not self.sales_person_id.account_receivable_id:
            raise ValidationError(
                ("The salesperson does not have a receivable account set.")
            )

        for line in self.order_lines:
            p = line.product_id
            if not p.income_account_id:
                raise ValidationError(
                    ("Income account missing for product: %s") % p.display_name
                )
            if not p.asset_account_id:
                raise ValidationError(
                    ("Asset (inventory) account missing for product: %s")
                    % p.display_name
                )
            if not p.account_cogs_id:
                raise ValidationError(
                    ("COGS account missing for product: %s") % p.display_name
                )

            if p.is_sales_commissionable and p.commission <= 0:
                raise ValidationError(
                    ("Invalid commission for product: %s") % p.display_name
                )

            if line.quantity <= 0:
                raise ValidationError(
                    ("Quantity must be positive for product: %s") % p.display_name
                )

    def freeze_exchange_rate(self):
        self.ensure_one()
        if not self.currency_id:
            self.rate = 0.0
            return

        on_date = (self.order_date or fields.Datetime.now()).date()
        rate = self.env["res.currency.rate"].search(
            [
                ("currency_id", "=", self.currency_id.id),
                ("name", "=", on_date),
                ("company_id", "=", self.env.company.id),
            ],
            limit=1,
        )
        self.rate = rate.rate if rate else (self.rate or 0.0)

    def create_receipt_on_confirm(self):

        self.ensure_one()
        self.flush_model(["order_total"])
        due = float(self.order_total or 0.0)

        self.env["idil.sales.receipt"].create(
            {
                "sales_order_id": self.id,
                "due_amount": due,
                "receipt_date": self.order_date,
                "paid_amount": 0.0,
                "remaining_amount": due,
                "salesperson_id": self.sales_person_id.id,
            }
        )

    def create_movements_on_confirm(self):
        self.ensure_one()
        Movement = self.env["idil.product.movement"]
        for line in self.order_lines:
            Movement.create(
                {
                    "product_id": line.product_id.id,
                    "sale_order_id": self.id,
                    "movement_type": "out",
                    "quantity": line.quantity,  # keep positive; direction via movement_type
                    "date": self.order_date,
                    "source_document": self.name,
                    "sales_person_id": self.sales_person_id.id,
                }
            )

    def book_accounting_entry(self):
        try:
            with self.env.cr.savepoint():
                for order in self:
                    expected_currency = (
                        order.sales_person_id.account_receivable_id.currency_id
                    )

                    trx_source_id = self.env["idil.transaction.source"].search(
                        [("name", "=", "Sales Order")], limit=1
                    )
                    if not trx_source_id:
                        raise ValidationError(
                            ('Transaction source "Sales Order" not found.')
                        )

                    transaction_booking = self.env["idil.transaction_booking"].create(
                        {
                            "sales_person_id": order.sales_person_id.id,
                            "sale_order_id": order.id,
                            "trx_source_id": trx_source_id.id,
                            "Sales_order_number": order.id,
                            "payment_method": "bank_transfer",
                            "payment_status": "pending",
                            "trx_date": order.order_date,
                            "amount": order.order_total,
                            "rate": order.rate,
                        }
                    )

                    self.env[
                        "idil.salesperson.order.summary"
                    ].create_summary_from_order(order)

                    for line in order.order_lines:
                        product = line.product_id

                        bom_currency = (
                            product.bom_id.currency_id
                            if product.bom_id
                            else product.currency_id
                        )
                        amount_in_bom_currency = float(product.cost) * line.quantity
                        if bom_currency.name == "USD":
                            product_cost_amount = amount_in_bom_currency * order.rate
                        else:
                            product_cost_amount = amount_in_bom_currency

                        _logger.info(
                            "Product Cost Amount: %s for product %s",
                            product_cost_amount,
                            product.name,
                        )

                        if line.commission_amount > 0:
                            if not product.sales_account_id:
                                raise ValidationError(
                                    (
                                        "Product '%s' has a commission amount but no Sales Commission Account set."
                                    )
                                    % product.name
                                )
                            if (
                                product.sales_account_id.currency_id
                                != expected_currency
                            ):
                                raise ValidationError(
                                    (
                                        "Sales Commission Account for product '%(p)s' has a different currency. "
                                        "Expected: %(ex)s, Actual: %(ac)s."
                                    )
                                    % {
                                        "p": product.name,
                                        "ex": expected_currency.name,
                                        "ac": product.sales_account_id.currency_id.name,
                                    }
                                )

                        if line.discount_amount > 0:
                            if not product.sales_discount_id:
                                raise ValidationError(
                                    (
                                        "Product '%s' has a discount amount but no Sales Discount Account set."
                                    )
                                    % product.name
                                )
                            if (
                                product.sales_discount_id.currency_id
                                != expected_currency
                            ):
                                raise ValidationError(
                                    (
                                        "Sales Discount Account for product '%(p)s' has a different currency. "
                                        "Expected: %(ex)s, Actual: %(ac)s."
                                    )
                                    % {
                                        "p": product.name,
                                        "ex": expected_currency.name,
                                        "ac": product.sales_discount_id.currency_id.name,
                                    }
                                )

                        if not product.asset_account_id:
                            raise ValidationError(
                                ("Product '%s' does not have an Asset Account set.")
                                % product.name
                            )
                        if product.asset_account_id.currency_id != expected_currency:
                            raise ValidationError(
                                (
                                    "Asset Account for product '%(p)s' has a different currency. "
                                    "Expected: %(ex)s, Actual: %(ac)s."
                                )
                                % {
                                    "p": product.name,
                                    "ex": expected_currency.name,
                                    "ac": product.asset_account_id.currency_id.name,
                                }
                            )

                        if not product.income_account_id:
                            raise ValidationError(
                                ("Product '%s' does not have an Income Account set.")
                                % product.name
                            )
                        if product.income_account_id.currency_id != expected_currency:
                            raise ValidationError(
                                (
                                    "Income Account for product '%(p)s' has a different currency. "
                                    "Expected: %(ex)s, Actual: %(ac)s."
                                )
                                % {
                                    "p": product.name,
                                    "ex": expected_currency.name,
                                    "ac": product.income_account_id.currency_id.name,
                                }
                            )

                        # DR COGS
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": transaction_booking.id,
                                "sale_order_id": order.id,
                                "description": f"Sales Order -- Expanses COGS account for - {product.name}",
                                "product_id": product.id,
                                "account_number": product.account_cogs_id.id,
                                "transaction_type": "dr",
                                "dr_amount": float(product_cost_amount),
                                "cr_amount": 0,
                                "rate": order.rate,
                                "transaction_date": order.order_date,
                            }
                        )
                        # CR Inventory
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": transaction_booking.id,
                                "sale_order_id": order.id,
                                "description": f"Sales Inventory account for - {product.name}",
                                "product_id": product.id,
                                "account_number": product.asset_account_id.id,
                                "transaction_type": "cr",
                                "dr_amount": 0,
                                "cr_amount": float(product_cost_amount),
                                "rate": order.rate,
                                "transaction_date": order.order_date,
                            }
                        )
                        # DR Receivable
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": transaction_booking.id,
                                "sale_order_id": order.id,
                                "description": f"Sale of {product.name}",
                                "product_id": product.id,
                                "account_number": order.sales_person_id.account_receivable_id.id,
                                "transaction_type": "dr",
                                "dr_amount": float(line.subtotal),
                                "cr_amount": 0,
                                "rate": order.rate,
                                "transaction_date": order.order_date,
                            }
                        )
                        # CR Revenue
                        self.env["idil.transaction_bookingline"].create(
                            {
                                "transaction_booking_id": transaction_booking.id,
                                "sale_order_id": order.id,
                                "description": f"Sales Revenue - {product.name}",
                                "product_id": product.id,
                                "account_number": product.income_account_id.id,
                                "transaction_type": "cr",
                                "dr_amount": 0,
                                "cr_amount": float(
                                    line.subtotal
                                    + line.commission_amount
                                    + line.discount_amount
                                ),
                                "rate": order.rate,
                                "transaction_date": order.order_date,
                            }
                        )

                        # DR Commission expense
                        if (
                            product.is_sales_commissionable
                            and line.commission_amount > 0
                        ):
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": transaction_booking.id,
                                    "sale_order_id": order.id,
                                    "description": f"Commission Expense - {product.name}",
                                    "product_id": product.id,
                                    "account_number": product.sales_account_id.id,
                                    "transaction_type": "dr",
                                    "dr_amount": float(line.commission_amount),
                                    "cr_amount": 0,
                                    "rate": order.rate,
                                    "transaction_date": order.order_date,
                                }
                            )

                        # DR Discount expense
                        if line.discount_amount > 0:
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": transaction_booking.id,
                                    "sale_order_id": order.id,
                                    "description": f"Discount Expense - {product.name}",
                                    "product_id": product.id,
                                    "account_number": product.sales_discount_id.id,
                                    "transaction_type": "dr",
                                    "dr_amount": line.discount_amount,
                                    "cr_amount": 0,
                                    "rate": order.rate,
                                    "transaction_date": order.order_date,
                                }
                            )
        except Exception as e:
            _logger.error("transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    def write(self, vals):
        try:
            with self.env.cr.savepoint():
                for order in self:
                    receipts = self.env["idil.sales.receipt"].search(
                        [("sales_order_id", "=", order.id), ("paid_amount", ">", 0)]
                    )
                    if receipts:
                        receipt_details = "\n".join(
                            [
                                f"- Receipt Date: {format_datetime(self.env, r.receipt_date)}, "
                                f"Amount Paid: {r.paid_amount:.2f}, Due: {r.due_amount:.2f}, Remaining: {r.remaining_amount:.2f}"
                                for r in receipts
                            ]
                        )
                        raise UserError(
                            (
                                "Cannot edit this Sales Order because it has linked Receipts:\n%s"
                            )
                            % receipt_details
                        )

                    returns = self.env["idil.sale.return"].search(
                        [("sale_order_id", "=", order.id)]
                    )
                    if returns:
                        return_details = "\n".join(
                            [
                                f"- Return Date: {format_datetime(self.env, r.return_date)}, State: {r.state}"
                                for r in returns
                            ]
                        )
                        raise UserError(
                            (
                                "Cannot edit this Sales Order because it has linked Sale Returns:\n%s"
                            )
                            % return_details
                        )

                for order in self:
                    old_quantities = {
                        line.id: line.quantity for line in order.order_lines
                    }

                for order in self:
                    for line in order.order_lines:
                        _ = line.product_id  # no-op, logic preserved
                        old_qty = old_quantities.get(line.id, 0.0)
                        new_qty = line.quantity
                        qty_diff = new_qty - old_qty  # kept for parity

                    res = super(SaleOrder, self).write(vals)

                    movements = self.env["idil.product.movement"].search(
                        [("sale_order_id", "=", order.id)]
                    )
                    movements.unlink()

                    for line in order.order_lines:
                        self.env["idil.product.movement"].create(
                            {
                                "sale_order_id": order.id,
                                "product_id": line.product_id.id,
                                "movement_type": "out",
                                "quantity": line.quantity * -1,
                                "date": order.order_date,
                                "source_document": order.name,
                                "sales_person_id": order.sales_person_id.id,
                            }
                        )

                    bookings = self.env["idil.transaction_booking"].search(
                        [("sale_order_id", "=", order.id)]
                    )
                    for booking in bookings:
                        booking.booking_lines.unlink()
                        booking.unlink()

                    order.book_accounting_entry()

                    receipt = self.env["idil.sales.receipt"].search(
                        [("sales_order_id", "=", order.id)], limit=1
                    )
                    if receipt:
                        paid_amount = receipt.paid_amount or 0.0
                        new_due = order.order_total
                        receipt.write(
                            {
                                "due_amount": new_due,
                                "remaining_amount": new_due - paid_amount,
                            }
                        )

                return res
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError("Transaction failed: %s") % e

    def unlink(self):
        try:
            with self.env.cr.savepoint():
                order_ids = self.ids
                for order in self:
                    receipts = self.env["idil.sales.receipt"].search(
                        [("sales_order_id", "=", order.id)]
                    )
                    receipts_with_payment = receipts.filtered(
                        lambda r: r.paid_amount > 0
                    )
                    if receipts_with_payment:
                        receipt_details = "\n".join(
                            [
                                f"- Receipt Date: {format_datetime(self.env, r.receipt_date)}, "
                                f"Amount Paid: {r.paid_amount:.2f}, Due: {r.due_amount:.2f}, Remaining: {r.remaining_amount:.2f}"
                                for r in receipts_with_payment
                            ]
                        )
                        raise UserError(
                            (
                                "Cannot edit this Sales Order because it has Receipts with payment:\n%s"
                            )
                            % receipt_details
                        )

                    returns = self.env["idil.sale.return"].search(
                        [("sale_order_id", "=", order.id)]
                    )
                    if returns:
                        return_details = "\n".join(
                            [
                                f"- Return Date: {format_datetime(self.env, r.return_date)}, State: {r.state}"
                                for r in returns
                            ]
                        )
                        raise UserError(
                            (
                                "Cannot edit this Sales Order because it has linked Sale Returns:\n%s"
                            )
                            % return_details
                        )
                res = super(SaleOrder, self).unlink()

                return res
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)


class SaleOrderLine(models.Model):
    _name = "idil.sale.order.line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Sale Order Line"
    _sql_constraints = [
        ("qty_positive", "CHECK(quantity > 0)", "Quantity must be positive."),
    ]

    company_id = fields.Many2one(related="order_id.company_id", store=True, index=True)
    # 🔧 NEW: give Monetary fields a currency on the line
    currency_id = fields.Many2one(
        "res.currency",
        related="order_id.currency_id",
        store=True,
        readonly=True,
        string="Currency",
    )
    order_id = fields.Many2one(
        "idil.sale.order", required=True, ondelete="cascade", index=True
    )

    product_id = fields.Many2one("my_product.product", string="Product")
    quantity_Demand = fields.Float(string="Demand", default=1.0)
    quantity = fields.Float(string="QTY Used", required=True, tracking=True)
    quantity_diff = fields.Float(
        string="QTY Diff", compute="_compute_quantity_diff", store=True
    )

    price_unit = fields.Float(
        string="Unit Price",
        default=lambda self: self.product_id.sale_price if self.product_id else 0.0,
    )
    commission = fields.Float(
        string="Commission %",
        default=lambda self: self.product_id.commission if self.product_id else 0.0,
    )
    # discount_amount = fields.Float(
    #     string="Discount Amount", compute="_compute_discount_amount", store=True
    # )

    subtotal = fields.Monetary(
        currency_field="currency_id", compute="_compute_subtotal"
    )
    discount_amount = fields.Monetary(
        currency_field="currency_id", compute="_compute_discount_amount", store=True
    )

    commission_amount = fields.Monetary(
        currency_field="currency_id",
        string="Commission Amount",
        compute="_compute_commission_amount",
        inverse="_set_commission_amount",
        store=True,
    )

    # subtotal = fields.Float(string="Due Amount", compute="_compute_subtotal")

    # commission_amount = fields.Float(
    #     string="Commission Amount",
    #     compute="_compute_commission_amount",
    #     inverse="_set_commission_amount",
    #     store=True,
    # )

    discount_quantity = fields.Float(
        string="Discount Quantity", compute="_compute_discount_quantity", store=True
    )
    returned_quantity = fields.Float(
        string="Returned Quantity",
        compute="_compute_returned_quantity",
        store=False,
        readonly=True,
    )

    @api.depends("order_id", "product_id")
    def _compute_returned_quantity(self):
        for line in self:
            if line.order_id and line.product_id:
                return_lines = self.env["idil.sale.return.line"].search(
                    [
                        ("return_id.sale_order_id", "=", line.order_id.id),
                        ("product_id", "=", line.product_id.id),
                        ("return_id.state", "=", "confirmed"),
                    ]
                )
                line.returned_quantity = sum(return_lines.mapped("returned_quantity"))
            else:
                line.returned_quantity = 0.0

    @api.depends("quantity", "product_id.commission", "price_unit", "commission")
    def _compute_commission_amount(self):
        for line in self:
            product = line.product_id
            if product.is_sales_commissionable:
                if not product.sales_account_id:
                    raise ValidationError(
                        ("Product '%s' does not have a Sales Commission Account set.")
                        % product.name
                    )
                if product.commission <= 0:
                    raise ValidationError(
                        ("Product '%s' does not have a valid Commission Rate set.")
                        % product.name
                    )

                line.commission_amount = (
                    (line.quantity - line.discount_quantity)
                    * line.commission
                    * line.price_unit
                )
            else:
                line.commission_amount = 0.0

    def _set_commission_amount(self):
        for line in self:
            pass

    @api.depends("quantity", "price_unit", "commission_amount")
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = (
                (line.quantity * line.price_unit)
                - (line.discount_quantity * line.price_unit)
                - line.commission_amount
            )

    @api.depends("quantity")
    def _compute_discount_quantity(self):
        for line in self:
            line.discount_quantity = (
                (line.product_id.discount / 100) * (line.quantity)
                if line.product_id.is_quantity_discount
                else 0.0
            )

    @api.depends("discount_quantity", "price_unit")
    def _compute_discount_amount(self):
        for line in self:
            line.discount_amount = line.discount_quantity * line.price_unit

    @api.depends("quantity_Demand", "quantity")
    def _compute_quantity_diff(self):
        for record in self:
            record.quantity_diff = record.quantity_Demand - record.quantity

    @api.model
    def create(self, vals):
        try:
            with self.env.cr.savepoint():
                return super(SaleOrderLine, self).create(vals)
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    def write(self, vals):
        try:
            with self.env.cr.savepoint():
                for line in self:
                    order = line.order_id
                    product = line.product_id
                    old_qty = line.quantity
                    new_qty = vals.get("quantity", old_qty)

                    if new_qty < old_qty:
                        confirmed_returns = self.env["idil.sale.return.line"].search(
                            [
                                ("return_id.sale_order_id", "=", order.id),
                                ("product_id", "=", product.id),
                                ("return_id.state", "=", "confirmed"),
                            ]
                        )
                        total_returned = sum(
                            confirmed_returns.mapped("returned_quantity")
                        )

                        if new_qty < total_returned:
                            raise ValidationError(
                                (
                                    "You cannot reduce quantity of '%(p)s' to %(n).2f because %(r).2f has already been returned."
                                )
                                % {"p": product.name, "n": new_qty, "r": total_returned}
                            )

                    if "quantity" in vals:
                        quantity_diff = vals["quantity"] - line.quantity
                        self.update_product_stock(line.product_id, quantity_diff)

                res = super(SaleOrderLine, self).write(vals)

                for line in self:
                    order = line.order_id

                    self.env["idil.salesperson.transaction"].search(
                        [("order_id", "=", order.id), ("sale_return_id", "=", False)]
                    ).unlink()

                    for updated_line in order.order_lines:
                        self.env["idil.salesperson.transaction"].create(
                            {
                                "sales_person_id": order.sales_person_id.id,
                                "date": fields.Date.today(),
                                "order_id": order.id,
                                "transaction_type": "out",
                                "amount": updated_line.subtotal
                                + updated_line.discount_amount
                                + updated_line.commission_amount,
                                "description": f"Sales Amount of - Order Line for {updated_line.product_id.name} (Qty: {updated_line.quantity})",
                            }
                        )

                        self.env["idil.salesperson.transaction"].create(
                            {
                                "sales_person_id": order.sales_person_id.id,
                                "date": fields.Date.today(),
                                "order_id": order.id,
                                "transaction_type": "in",
                                "amount": updated_line.commission_amount,
                                "description": f"Sales Commission Amount of - Order Line for {updated_line.product_id.name} (Qty: {updated_line.quantity})",
                            }
                        )

                        self.env["idil.salesperson.transaction"].create(
                            {
                                "sales_person_id": order.sales_person_id.id,
                                "date": fields.Date.today(),
                                "order_id": order.id,
                                "transaction_type": "in",
                                "amount": updated_line.discount_amount,
                                "description": f"Sales Discount Amount of - Order Line for {updated_line.product_id.name} (Qty: {updated_line.quantity})",
                            }
                        )

                return res
        except Exception as e:
            _logger.error("Create transaction failed: %s", e)
            raise ValidationError(("Transaction failed: %s") % e)

    @staticmethod
    def update_product_stock(product, quantity_diff):
        new_stock_quantity = product.stock_quantity - quantity_diff
        if new_stock_quantity < 0:
            raise ValidationError(
                (
                    "Insufficient stock for product '%(p)s'. The available stock quantity is %(a).2f, "
                    "but the required quantity is %(r).2f."
                )
                % {
                    "p": product.name,
                    "a": product.stock_quantity,
                    "r": abs(quantity_diff),
                }
            )
        # product.stock_quantity = new_stock_quantity
