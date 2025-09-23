/** @odoo-module **/
import { Component, onWillStart, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class IdilDashboard extends Component {
    setup() {
        this.rpc = useService("rpc");
        this.stats = { total_sales: 0, total_purchases: 0, total_customers: 0 };

        onWillStart(async () => {
            await this.fetchStats();
        });

        onMounted(() => {
            this.refreshInterval = setInterval(() => this.fetchStats(), 5000); // refresh every 5 sec
        });
    }

    async fetchStats() {
        this.stats = await this.rpc('/idil/dashboard/stats');
        this.render();
    }

    willUnmount() {
        clearInterval(this.refreshInterval);
    }
}
IdilDashboard.template = "idil.IdilDashboardTemplate";

// Register in action service
registry.category("actions").add("idil_dashboard_action", IdilDashboard);
