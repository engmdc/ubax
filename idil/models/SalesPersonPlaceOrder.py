from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError


class SalespersonOrder(models.Model):
    _name = "idil.salesperson.place.order"
    _description = "Salesperson Place Order"
    _order = "id desc"

    salesperson_id = fields.Many2one(
        "idil.sales.sales_personnel", string="Salesperson", required=True
    )
    order_date = fields.Datetime(string="Order Date", default=fields.Datetime.now)
    order_lines = fields.One2many(
        "idil.salesperson.place.order.line", "order_id", string="Order Lines"
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancel", "Cancelled")],
        default="draft",
    )
    total_quantity = fields.Float(
        string="Total Quantity", compute="_compute_total_quantity", store=True
    )

    @api.depends("order_lines.quantity")
    def _compute_total_quantity(self):
        for order in self:
            order.total_quantity = sum(line.quantity for line in order.order_lines)

    @api.model
    def create(self, vals):
        existing_draft_order = self.search(
            [
                ("salesperson_id", "=", vals.get("salesperson_id")),
                ("state", "=", "draft"),
            ],
            limit=1,
        )

        if existing_draft_order:
            raise UserError(
                "This salesperson already has an active draft order. "
                "Please edit the existing order or change its state before creating a new one."
            )

        order = super(SalespersonOrder, self).create(vals)
        # Create summary entries after the order is created

        return order

    def write(self, vals):
        for record in self:
            # Allow pure state change (e.g., SO confirming this place order)
            only_state_change = set(vals.keys()) <= {"state"}
            if not only_state_change:
                # If not a pure state change, block edits when already linked to a confirmed SO
                sale_orders = self.env["idil.sale.order"].search(
                    [
                        ("salesperson_order_id", "=", record.id),  # <- FIXED COMMA HERE
                        ("state", "=", "confirmed"),
                    ],
                    limit=1,
                )
                if sale_orders:
                    raise UserError(
                        "This Salesperson Order is already linked to a confirmed Sales Order and cannot be edited."
                    )
        return super(SalespersonOrder, self).write(vals)

    def unlink(self):
        for record in self:
            # Prevent delete if a related sale order exists
            sale_orders = self.env["idil.sale.order"].search(
                [("salesperson_order_id", "=", record.id)]
            )
            if sale_orders:
                raise UserError(
                    "This Salesperson Order is already linked to a Sales Order and cannot be deleted."
                )
        return super(SalespersonOrder, self).unlink()

    def action_confirm_order(self):
        self.write({"state": "confirmed"})


class SalespersonOrderLine(models.Model):
    _name = "idil.salesperson.place.order.line"
    _description = "Salesperson Place Order Line"

    order_id = fields.Many2one(
        "idil.salesperson.place.order", string="Salesperson Order"
    )
    product_id = fields.Many2one("my_product.product", string="Product", required=True)
    quantity = fields.Float(string="Quantity", default=1.0)

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.quantity = 1.0

    @api.constrains("quantity")
    def _check_quantity(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")


class SalespersonOrderSummary(models.Model):
    _name = "idil.salesperson.order.summary"
    _description = "Salesperson Order Summary"
    _order = "id desc"

    salesperson_name = fields.Char(string="Salesperson Name", required=True)
    product_name = fields.Char(string="Product Name", required=True)
    quantity = fields.Float(string="Quantity", required=True)
    order_date = fields.Datetime(string="Order Date", required=True)
    sale_order_id = fields.Many2one(
        "idil.sale.order", string="Related Sale Order", ondelete="cascade"
    )

    @api.model
    def create_summary_from_order(self, order):
        for line in order.order_lines:
            self.create(
                {
                    "salesperson_name": order.sales_person_id.name,
                    "product_name": line.product_id.name,
                    "quantity": line.quantity,
                    "order_date": order.order_date,
                    "sale_order_id": order.id,  # ✅ Add this
                }
            )

    @api.model
    def update_summary_from_order(self, order):
        # Delete existing summary entries for this order
        self.search(
            [
                ("order_date", "=", order.order_date),
                ("salesperson_name", "=", order.salesperson_id.name),
            ]
        ).unlink()
        # Recreate summary entries based on updated order
        self.create_summary_from_order(order)

    @api.model
    def delete_summary_from_order(self, order):
        # Logic to delete summary entries corresponding to the order
        # Remove related summary lines
        self.env["idil.salesperson.order.summary"].search(
            [("sale_order_id", "=", order.id)]
        ).unlink()
