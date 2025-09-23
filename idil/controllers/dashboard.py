from odoo import http
from odoo.http import request


class IdilDashboardController(http.Controller):

    @http.route("/idil/dashboard/stats", auth="user", type="json")
    def get_dashboard_stats(self):
        SaleOrder = request.env["idil.sale.order"].sudo()
        PurchaseOrder = request.env["idil.purchase_order"].sudo()
        Customer = request.env["idil.customer.registration"].sudo()
        return {
            "total_sales": SaleOrder.search_count([]),
            "total_purchases": PurchaseOrder.search_count([]),
            "total_customers": Customer.search_count([]),
        }
