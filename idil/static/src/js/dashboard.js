odoo.define('idil_dashboard.dashboard_auto_refresh', function (require) {
    "use strict";

    const KanbanController = require('web.KanbanController');
    const KanbanView = require('web.KanbanView');
    const viewRegistry = require('web.view_registry');

    const DashboardController = KanbanController.extend({
        start() {
            this._super(...arguments);
            setInterval(() => this.reload(), 10000);  // 10s refresh
        }
    });

    const DashboardView = KanbanView.extend({
        config: Object.assign({}, KanbanView.prototype.config, {
            Controller: DashboardController,
        }),
    });

    viewRegistry.add('idil_dashboard_kanban', DashboardView);
});
