# -*- coding: utf-8 -*-
from odoo import models, fields, tools


class IdilReportProductionSummary(models.Model):
    _name = "idil.report.production.summary"
    _description = "Production Summary (per MO)"
    _auto = False
    _rec_name = "order_name"

    date = fields.Date(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    order_id = fields.Many2one("idil.manufacturing.order", string="MO", readonly=True)
    order_name = fields.Char(string="Order Ref", readonly=True)
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        readonly=True,
    )

    product_qty = fields.Float(string="Produced Qty", digits=(16, 5), readonly=True)
    bom_grand_total = fields.Float(
        string="BOM Grand Total (USD)", digits=(16, 6), readonly=True
    )
    product_cost = fields.Float(
        string="Product Cost (USD)", digits=(16, 6), readonly=True
    )
    rate = fields.Float(string="Rate", digits=(16, 6), readonly=True)
    product_cost_sos = fields.Float(
        string="Product Cost (SOS)", digits=(16, 6), readonly=True
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "idil_report_production_summary")
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW idil_report_production_summary AS
            SELECT
                mo.id AS id,
                mo.id AS order_id,
                mo.name AS order_name,
                mo.company_id,
                mo.product_id,
                mo.status,
                DATE(mo.scheduled_start_date) AS date,
                COALESCE(mo.product_qty,0.0) AS product_qty,
                COALESCE(mo.bom_grand_total,0.0) AS bom_grand_total,
                COALESCE(mo.product_cost,0.0) AS product_cost,
                COALESCE(mo.rate,0.0) AS rate,
                COALESCE(mo.product_cost,0.0) * COALESCE(mo.rate,0.0) AS product_cost_sos
            FROM idil_manufacturing_order mo
        """
        )


# -*- coding: utf-8 -*-


class IdilReportMaterialEfficiency(models.Model):
    _name = "idil.report.material.efficiency"
    _description = "Material Usage vs BOM (per MO)"
    _auto = False
    _rec_name = "order_name"

    date = fields.Date(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    order_id = fields.Many2one("idil.manufacturing.order", string="MO", readonly=True)
    order_name = fields.Char(string="Order Ref", readonly=True)
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)

    material_used_qty = fields.Float(string="Used Qty", digits=(16, 5), readonly=True)
    material_demand_qty = fields.Float(
        string="BOM Demand", digits=(16, 5), readonly=True
    )
    variance_qty = fields.Float(string="Variance Qty", digits=(16, 5), readonly=True)
    variance_pct = fields.Float(string="Variance %", digits=(16, 4), readonly=True)

    material_cost_usd = fields.Float(
        string="Materials USD", digits=(16, 6), readonly=True
    )
    material_cost_sos = fields.Float(
        string="Materials SOS", digits=(16, 6), readonly=True
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "idil_report_material_efficiency")
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW idil_report_material_efficiency AS
            SELECT
                mo.id AS id,
                mo.id AS order_id,
                mo.name AS order_name,
                mo.company_id,
                mo.product_id,
                DATE(mo.scheduled_start_date) AS date,

                COALESCE(SUM(ml.quantity),0.0) AS material_used_qty,
                COALESCE(SUM(ml.quantity_bom),0.0) AS material_demand_qty,
                COALESCE(SUM(ml.quantity),0.0) - COALESCE(SUM(ml.quantity_bom),0.0) AS variance_qty,
                CASE
                    WHEN COALESCE(SUM(ml.quantity_bom),0.0) = 0.0 THEN 0.0
                    ELSE ((COALESCE(SUM(ml.quantity),0.0) - COALESCE(SUM(ml.quantity_bom),0.0))
                         / NULLIF(COALESCE(SUM(ml.quantity_bom),0.0),0.0)) * 100.0
                END AS variance_pct,

                COALESCE(SUM(ml.row_total),0.0) AS material_cost_usd,
                COALESCE(SUM(ml.cost_amount_sos),0.0) AS material_cost_sos
            FROM idil_manufacturing_order mo
            JOIN idil_manufacturing_order_line ml
              ON ml.manufacturing_order_id = mo.id
            GROUP BY mo.id, mo.name, mo.company_id, mo.product_id, DATE(mo.scheduled_start_date)
        """
        )


# -*- coding: utf-8 -*-


class IdilReportFinancialSummary(models.Model):
    _name = "idil.report.financial.summary"
    _description = "Financial Summary (per MO)"
    _auto = False
    _rec_name = "order_name"

    date = fields.Date(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    order_id = fields.Many2one("idil.manufacturing.order", string="MO", readonly=True)
    order_name = fields.Char(string="Order Ref", readonly=True)
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)

    product_cost = fields.Float(
        string="Product Cost (USD)", digits=(16, 6), readonly=True
    )
    rate = fields.Float(string="Rate", digits=(16, 6), readonly=True)
    product_cost_sos = fields.Float(
        string="Product Cost (SOS)", digits=(16, 6), readonly=True
    )
    material_cost_usd = fields.Float(
        string="Materials USD", digits=(16, 6), readonly=True
    )
    material_cost_sos = fields.Float(
        string="Materials SOS", digits=(16, 6), readonly=True
    )
    commission_amount = fields.Float(string="Commission", digits=(16, 6), readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "idil_report_financial_summary")
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW idil_report_financial_summary AS
            WITH mat AS (
                SELECT
                    mo.id AS mo_id,
                    SUM(ml.row_total) AS mat_usd,
                    SUM(ml.cost_amount_sos) AS mat_sos
                FROM idil_manufacturing_order mo
                JOIN idil_manufacturing_order_line ml
                  ON ml.manufacturing_order_id = mo.id
                GROUP BY mo.id
            )
            SELECT
                mo.id AS id,
                mo.id AS order_id,
                mo.name AS order_name,
                mo.company_id,
                mo.product_id,
                DATE(mo.scheduled_start_date) AS date,
                COALESCE(mo.product_cost,0.0) AS product_cost,
                COALESCE(mo.rate,0.0) AS rate,
                COALESCE(mo.product_cost,0.0) * COALESCE(mo.rate,0.0) AS product_cost_sos,
                COALESCE(mat.mat_usd,0.0) AS material_cost_usd,
                COALESCE(mat.mat_sos,0.0) AS material_cost_sos,
                COALESCE(mo.commission_amount,0.0) AS commission_amount
            FROM idil_manufacturing_order mo
            LEFT JOIN mat ON mat.mo_id = mo.id
        """
        )


# -*- coding: utf-8 -*-


class IdilReportCommissionOverview(models.Model):
    _name = "idil.report.commission.overview"
    _description = "Commission Overview (per MO)"
    _auto = False
    _rec_name = "order_name"

    date = fields.Date(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    order_id = fields.Many2one("idil.manufacturing.order", string="MO", readonly=True)
    order_name = fields.Char(string="Order Ref", readonly=True)
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)
    employee_id = fields.Many2one(
        "idil.employee", string="Commission Employee", readonly=True
    )

    commission_amount = fields.Float(
        string="Commission Amount", digits=(16, 6), readonly=True
    )
    commission_to_cost_ratio = fields.Float(
        string="Commission / Product Cost %", digits=(16, 4), readonly=True
    )

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "idil_report_commission_overview")
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW idil_report_commission_overview AS
            SELECT
                mo.id AS id,
                mo.id AS order_id,
                mo.name AS order_name,
                mo.company_id,
                mo.product_id,
                mo.commission_employee_id AS employee_id,
                DATE(mo.scheduled_start_date) AS date,
                COALESCE(mo.commission_amount,0.0) AS commission_amount,
                CASE
                    WHEN COALESCE(mo.product_cost,0.0) = 0.0 THEN 0.0
                    ELSE (COALESCE(mo.commission_amount,0.0) / mo.product_cost) * 100.0
                END AS commission_to_cost_ratio
            FROM idil_manufacturing_order mo
        """
        )


# -*- coding: utf-8 -*-


class IdilReportMovements(models.Model):
    _name = "idil.report.movements"
    _description = "Manufacturing Movements (In/Out)"
    _auto = False
    _rec_name = "doc"

    date = fields.Datetime(readonly=True)
    company_id = fields.Many2one("res.company", readonly=True)
    mo_id = fields.Many2one("idil.manufacturing.order", string="MO", readonly=True)

    doc = fields.Char(string="Document", readonly=True)
    movement_type = fields.Selection([("in", "In"), ("out", "Out")], readonly=True)
    product_id = fields.Many2one("my_product.product", string="Product", readonly=True)
    item_id = fields.Many2one("idil.item", string="Item", readonly=True)
    quantity = fields.Float(string="Qty", digits=(16, 5), readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, "idil_report_movements")
        self.env.cr.execute(
            """
            CREATE OR REPLACE VIEW idil_report_movements AS
            SELECT
                pm.id AS id,
                pm.date AS date,
                mo.company_id,
                mo.id AS mo_id,
                pm.source_document AS doc,
                'in'::varchar AS movement_type,
                pm.product_id,
                NULL::int4 AS item_id,
                COALESCE(pm.quantity,0.0) AS quantity
            FROM idil_product_movement pm
            LEFT JOIN idil_manufacturing_order mo ON mo.id = pm.manufacturing_order_id

            UNION ALL

            SELECT
                im.id * 1000000 AS id,  -- ensure uniqueness across union
                im.date AS date,
                mo.company_id,
                mo.id AS mo_id,
                im.related_document AS doc,
                'out'::varchar AS movement_type,
                NULL::int4 AS product_id,
                im.item_id,
                COALESCE(im.quantity,0.0) AS quantity
            FROM idil_item_movement im
            LEFT JOIN idil_manufacturing_order mo ON mo.id = im.manufacturing_order_id
        """
        )
