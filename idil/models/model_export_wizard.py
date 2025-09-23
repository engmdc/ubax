# models/model_export_wizard.py
from odoo import models, fields, api
from odoo.exceptions import UserError
import base64
import io
import xlsxwriter


class ModelExportWizard(models.TransientModel):
    _name = "model.export.wizard"
    _description = "Export Model Data to Excel"

    model_name = fields.Selection(
        selection=lambda self: self._get_model_selection(),
        string="Model",
        required=True,
    )
    field_ids = fields.Many2many(
        "ir.model.fields",
        string="Fields to Export",
        required=True,
        domain="[('store', '=', True), ('ttype', 'not in', ('one2many', 'many2many')), ('name', 'not like', '_%')]",
    )
    file_name = fields.Char(string="Filename")
    file_data = fields.Binary(string="File", readonly=True)

    @api.onchange("model_name")
    def _onchange_model_name(self):
        if self.model_name:
            fields_model = self.env["ir.model.fields"].search(
                [
                    ("model", "=", self.model_name),
                    ("store", "=", True),
                    ("ttype", "not in", ["one2many", "many2many"]),
                    ("name", "not like", "_%"),
                    ("compute", "=", False),
                ]
            )
            self.field_ids = [
                (6, 0, fields_model.ids)
            ]  # <-- This preselects all fields
            return {"domain": {"field_ids": [("id", "in", fields_model.ids)]}}

    def _get_model_selection(self):
        models = self.env["ir.model"].search([])
        return [
            (m.model, m.name)
            for m in models
            if m.model.startswith("idil.") or m.model.startswith("my_product.")
        ]

    def export_excel(self):
        if not self.model_name or not self.field_ids:
            raise UserError("Model or fields not selected.")

        model = self.env[self.model_name]
        fields_list = self.field_ids.mapped("name")
        records = model.search([])
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {"in_memory": True})
        worksheet = workbook.add_worksheet("Export")

        # Header
        for col, field_name in enumerate(fields_list):
            worksheet.write(0, col, field_name)

        # Rows
        for row_idx, record in enumerate(records, start=1):
            for col_idx, field_name in enumerate(fields_list):
                try:
                    value = getattr(record, field_name)
                    if isinstance(value, models.BaseModel):
                        value = value.display_name
                except Exception:
                    value = "⚠️ Error"
                worksheet.write(row_idx, col_idx, str(value) if value else "")

        workbook.close()
        output.seek(0)

        self.write(
            {
                "file_name": f"{self.model_name.replace('.', '_')}_export.xlsx",
                "file_data": base64.b64encode(output.read()),
            }
        )

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/?model=model.export.wizard&id={self.id}&field=file_data&filename_field=file_name&download=true",
            "target": "new",
        }
