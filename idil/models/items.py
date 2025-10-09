from odoo import models, fields, api
from odoo.exceptions import ValidationError
from datetime import datetime

import logging

from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class item(models.Model):
    _name = "idil.item"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Idil Purchased Items"

    ITEM_TYPE_SELECTION = [
        ("service", "Service"),
        ("inventory", "Inventory"),
        ("non_inventory", "Non-Inventory"),
        ("discount", "Discount"),
        ("payment", "Payment"),
        ("tax", "Tax"),
        ("mileage", "Mileage"),
        # Add more QuickBooks item types as needed
    ]
    name = fields.Char(string="Item Name", required=True, tracking=True)
    active = fields.Boolean(string="Archive", default=True, tracking=True)

    description = fields.Text(string="Description", tracking=True)
    item_type = fields.Selection(
        selection=ITEM_TYPE_SELECTION, string="Item Type", required=True, tracking=True
    )

    quantity = fields.Float(
        string="Quantity",
        compute="_compute_stock_quantity",
        digits=(16, 5),
        store=False,  # do NOT store, so it reflects real-time movement
        help="Quantity in stock, computed from movement history (IN - OUT)",
    )

    purchase_date = fields.Date(
        string="Purchase Date", required=True, tracking=True, default=fields.Date.today
    )
    expiration_date = fields.Date(
        string="Expiration Date", required=True, tracking=True
    )
    item_category_id = fields.Many2one(
        comodel_name="idil.item.category",
        string="Item Category",
        required=True,
        help="Select Item Category",
        tracking=True,
    )
    unitmeasure_id = fields.Many2one(
        comodel_name="idil.unit.measure",
        string="Unit of Measure",
        required=True,
        help="Select Unit of Measure",
        tracking=True,
    )
    min = fields.Float(string="Min Order", required=True, tracking=True)

    cost_price = fields.Float(
        string="Price per Unit", digits=(16, 5), required=True, tracking=True
    )

    allergens = fields.Char(string="Allergens/Ingredients", tracking=True)
    image = fields.Binary(string=" Image")
    order_information = fields.Char(string="Order Information", tracking=True)
    bar_code = fields.Char(string="Bar Code", tracking=True)
    # Currency fields
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    purchase_account_id = fields.Many2one(
        "idil.chart.account",
        string="Purchase Account",
        help="Account to report purchases of this item",
        required=True,
        tracking=True,
        domain="[('account_type', 'like', 'COGS'), ('currency_id', '=', currency_id)]",
    )
    sales_account_id = fields.Many2one(
        "idil.chart.account",
        string="Sales Account",
        help="Account to report sales of this item",
        tracking=True,
        domain="[('code', 'like', '4'), ('currency_id', '=', currency_id)]",
        # Domain to filter accounts starting with '4' and in USD
    )
    asset_account_id = fields.Many2one(
        "idil.chart.account",
        string="Asset Account",
        help="Account to report Asset of this item",
        required=True,
        tracking=True,
        domain="[('code', 'like', '1'), ('currency_id', '=', currency_id)]",
        # Domain to filter accounts starting with '1' and in USD
    )

    adjustment_account_id = fields.Many2one(
        "idil.chart.account",
        string="Asset Account",
        help="Account to report adjustment of this item",
        required=True,
        tracking=True,
        domain="[('code', 'like', '1'), ('code', 'like', '5'), ('currency_id', '=', currency_id)]",
        # Domain to filter accounts starting with '1' and in USD
    )

    days_until_expiration = fields.Integer(
        string="Days Until Expiration",
        compute="_compute_days_until_expiration",
        store=True,
        readonly=True,
    )
    # New computed field
    total_price = fields.Float(
        string="Total Price",
        compute="compute_item_total_value",
        store=False,
        digits=(16, 5),
        tracking=True,
    )

    is_tfg = fields.Boolean(string="Is TFG", default=False, tracking=True)
    is_commission = fields.Boolean(string="Is Commission", default=False, tracking=True)

    # New field to track item movements
    movement_ids = fields.One2many(
        "idil.item.movement", "item_id", string="Item Movements"
    )

    @api.depends("movement_ids.quantity", "movement_ids.movement_type")
    def _compute_stock_quantity(self):
        for product in self:
            qty_in = sum(
                m.quantity for m in product.movement_ids if m.movement_type == "in"
            )
            qty_out = sum(
                m.quantity for m in product.movement_ids if m.movement_type == "out"
            )
            product.quantity = round(qty_in + qty_out, 5)

    # Add a method to update currency_id for existing records
    def update_currency_id(self):
        usd_currency = self.env.ref("base.USD")
        self.search([]).write({"currency_id": usd_currency.id})

    @api.depends_context("uid")
    def compute_item_total_value(self):
        """Compute total value per item: sum(dr_amount - cr_amount) where account is asset_account_id."""
        for item in self:
            item.total_price = 0.0  # Default value

            if not item.asset_account_id:
                continue

            self.env.cr.execute(
                """
                SELECT 
                    COALESCE(SUM(dr_amount), 0) - COALESCE(SUM(cr_amount), 0) AS balance
                FROM idil_transaction_bookingline
                WHERE item_id = %s AND account_number = %s
            """,
                (item.id, item.asset_account_id.id),
            )

            result = self.env.cr.fetchone()
            item.total_price = round(result[0], 5) if result and result[0] else 0.0

    @api.constrains("name")
    def _check_unique_name(self):
        for record in self:
            if self.search([("name", "=", record.name), ("id", "!=", record.id)]):
                raise ValidationError(
                    'Item name must be unique. The name "%s" is already in use.'
                    % record.name
                )

    @api.depends("expiration_date")
    def _compute_days_until_expiration(self):
        for record in self:
            if record.expiration_date:
                delta = record.expiration_date - fields.Date.today()
                record.days_until_expiration = delta.days
            else:
                record.days_until_expiration = 0

    @api.constrains("purchase_date", "expiration_date")
    def check_date_not_in_past(self):
        for record in self:
            today = fields.Date.today()
            if record.expiration_date < today:
                raise ValidationError(
                    "Expiration dates must be today or in the future."
                )

    @api.constrains("quantity", "cost_price")
    def _check_positive_values(self):
        for record in self:
            if record.quantity < 0:
                raise ValidationError("Quantity must be a positive value.")
            if record.cost_price < 0:
                raise ValidationError("Cost price must be a positive value.")

    def check_reorder(self):
        """Send notifications for items that need reordering."""
        for record in self:
            if record.quantity < record.min:
                # Logic to send notification or create a reorder
                record.message_post(
                    body=f"Item {record.name} needs reordering. Current stock: {record.quantity}"
                )


class ItemMovement(models.Model):
    _name = "idil.item.movement"
    _description = "Item Movement"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    item_id = fields.Many2one("idil.item", string="Item", required=True, tracking=True)
    date = fields.Date(
        string="Date", required=True, default=fields.Date.today, tracking=True
    )
    quantity = fields.Float(string="Quantity", required=True, tracking=True)
    source = fields.Char(string="Source", required=True, tracking=True)
    destination = fields.Char(string="Destination", required=True, tracking=True)
    movement_type = fields.Selection(
        [("in", "In"), ("out", "Out")],
        string="Movement Type",
        required=True,
        tracking=True,
    )
    related_document = fields.Reference(
        selection=[
            ("idil.purchase_order.line", "Purchase Order Line"),
            ("idil.manufacturing.order.line", "Manufacturing Order Line"),
            ("idil.stock.adjustment", "Stock Adjustment"),
            ("idil.purchase_return.line", "Purchase Return Line"),
            ("idil.item.opening.balance.line", "Item Opening Balance Line"),
        ],
        string="Related Document",
    )

    vendor_id = fields.Many2one(
        "idil.vendor.registration",
        string="Vendor",
        tracking=True,
        help="Vendor associated with this movement if it originated from a purchase order",
    )

    product_id = fields.Many2one(
        "my_product.product",
        string="Product",
        tracking=True,
        help="Product associated with this movement if it relates to a manufacturing order",
    )
    transaction_number = fields.Char(string="Transaction Number", tracking=True)

    purchase_order_line_id = fields.Many2one(
        "idil.purchase_order.line",
        string="Purchase Order Line",
        ondelete="cascade",  # Enables automatic deletion
        index=True,
    )
    item_opening_balance_id = fields.Many2one(
        "idil.item.opening.balance",
        string="Item Opening Balance",
        ondelete="cascade",  # ✅ auto-delete booking when opening balance is deleted
        index=True,
    )
    purchase_return_id = fields.Many2one(
        "idil.purchase_return",
        string="Purchase Return",
        ondelete="cascade",
    )

    manufacturing_order_line_id = fields.Many2one(
        "idil.manufacturing.order.line",
        string="Manufacturing Order Line",
        ondelete="cascade",  # DB cascades movements when the line is deleted
        index=True,
        tracking=True,
    )

    manufacturing_order_id = fields.Many2one(
        "idil.manufacturing.order",
        string="Manufacturing Order",
        ondelete="cascade",
        index=True,
        tracking=True,
    )

    @api.constrains("item_id", "movement_type", "quantity", "date")
    def _check_enough_stock_on_out(self):
        """
        Prevent negative stock for any OUT movement, evaluated as of the movement's date.
        Uses your formula: IN + OUT (where OUT is stored negative).
        """
        precision = 5  # matches digits=(16,5)

        for m in self:
            if not m.item_id or m.movement_type != "out":
                continue

            # Stock balance as of this movement (including it)
            self.env.cr.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN movement_type = 'in'  THEN quantity ELSE 0 END), 0)
                + COALESCE(SUM(CASE WHEN movement_type = 'out' THEN quantity ELSE 0 END), 0)
                FROM idil_item_movement
                WHERE item_id = %s
                AND (date < %s OR (date = %s AND id <= %s))
            """,
                (m.item_id.id, m.date, m.date, m.id),
            )
            (resulting_balance,) = self.env.cr.fetchone()
            resulting_balance = resulting_balance or 0.0

            # Balance BEFORE this record = after - this movement qty
            available_before = resulting_balance - (m.quantity or 0.0)

            if float_compare(resulting_balance, 0.0, precision_digits=precision) < 0:
                raise ValidationError(
                    "Insufficient stock for item '{name}' as of {date}. "
                    "Available: {avail:.5f} | Requested: {req:.5f} | "
                    "Resulting Balance: {res:.5f}".format(
                        name=m.item_id.name,
                        date=m.date,
                        avail=round(available_before, precision),
                        req=round(m.quantity or 0.0, precision),
                        res=round(resulting_balance, precision),
                    )
                )
