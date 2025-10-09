from venv import logger
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class JournalEntry(models.Model):
    _name = "idil.journal.entry"
    _description = "Journal Entry"
    _order = "id desc"

    company_id = fields.Many2one(
        "res.company", default=lambda s: s.env.company, required=True
    )

    name = fields.Char(
        string="Journal no",
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: _("New"),
    )
    partner_type = fields.Selection(
        [("vendor", "Vendor"), ("customer", "Customer"), ("others", "Others")],
        string="Type",
        required=True,
    )
    date = fields.Date(
        string="Journal Date", required=True, default=fields.Date.context_today
    )
    line_ids = fields.One2many(
        "idil.journal.entry.line", "entry_id", string="Journal Lines"
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )

    total_debit = fields.Monetary(
        string="Total Debit", compute="_compute_totals", store=True
    )
    total_credit = fields.Monetary(
        string="Total Credit", compute="_compute_totals", store=True
    )
    vendor_id = fields.Many2one(
        "idil.vendor.registration", string="Vendor", ondelete="restrict"
    )
    customer_id = fields.Many2one("idil.customer.registration", string="Customer")

    rate = fields.Float(
        string="Exchange Rate",
        compute="_compute_exchange_rate",
        store=True,
        readonly=True,
        tracking=True,
    )
    # 🆕 Add state field
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("confirmed", "Confirmed"),
            ("cancel", "Cancelled"),
        ],
        string="Status",
        default="confirmed",
        tracking=True,
    )

    @api.depends("currency_id", "date", "company_id")
    def _compute_exchange_rate(self):
        Rate = self.env["res.currency.rate"].sudo()
        for order in self:
            order.rate = 0.0
            if not order.currency_id:
                continue

            doc_date = (
                fields.Date.to_date(order.date) if order.date else fields.Date.today()
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

    @api.constrains("vendor_id", "customer_id")
    def _check_vendor_or_customer(self):
        for record in self:
            if record.vendor_id and record.customer_id:
                raise ValidationError(
                    _(
                        "You cannot select both Vendor and Customer on the same journal entry. Please choose only one."
                    )
                )

    @api.constrains("line_ids")
    def _check_minimum_lines(self):
        for record in self:
            lines = record.line_ids.filtered(lambda l: l.account_id)
            debit_lines = lines.filtered(lambda l: l.debit > 0)
            credit_lines = lines.filtered(lambda l: l.credit > 0)

            if len(lines) < 2:
                raise ValidationError(_("You must provide at least two journal lines."))
            if not debit_lines:
                raise ValidationError(
                    _("At least one journal line must have a debit amount.")
                )
            if not credit_lines:
                raise ValidationError(
                    _("At least one journal line must have a credit amount.")
                )

    @api.onchange("vendor_id")
    def _onchange_vendor_id(self):
        if self.vendor_id:
            self.customer_id = False

    @api.onchange("customer_id")
    def _onchange_customer_id(self):
        if self.customer_id:
            self.vendor_id = False

    @api.model
    def default_get(self, fields_list):
        res = super(JournalEntry, self).default_get(fields_list)
        if "line_ids" in fields_list:
            res.update({"line_ids": [(0, 0, {}) for _ in range(2)]})
        return res

    # --- helper: pick the right partner account ---
    def _get_partner_account(self):
        self.ensure_one()
        if (
            self.partner_type == "customer"
            and self.customer_id
            and getattr(self.customer_id, "account_receivable_id", False)
        ):
            return self.customer_id.account_receivable_id
        if (
            self.partner_type == "vendor"
            and self.vendor_id
            and getattr(self.vendor_id, "account_payable_id", False)
        ):
            return self.vendor_id.account_payable_id
        return False  # others or not set

    # --- helper: ensure 2 lines exist, set/clear the FIRST line account (safe during onchange) ---
    def _set_first_line_account(self, account):
        self.ensure_one()
        if not self.line_ids:
            # make sure we have two lines ready for the user
            self.line_ids = [(0, 0, {}), (0, 0, {})]
        first_line = self.line_ids[0]  # do NOT sort; NewId is not comparable
        first_line.account_id = account.id if account else False

    # --- react when type changes ---
    @api.onchange("partner_type")
    def _onchange_partner_type(self):
        # keep partners mutually exclusive for clarity
        if self.partner_type == "customer":
            self.vendor_id = False
        elif self.partner_type == "vendor":
            self.customer_id = False
        # set/clear first line based on the current type + selected partner
        self._set_first_line_account(self._get_partner_account())

    # --- react when customer chosen ---
    @api.onchange("customer_id")
    def _onchange_customer_id(self):
        if self.customer_id:
            self.vendor_id = False
        if self.partner_type == "customer":
            self._set_first_line_account(self._get_partner_account())

    # --- react when vendor chosen ---
    @api.onchange("vendor_id")
    def _onchange_vendor_id(self):
        if self.vendor_id:
            self.customer_id = False
        if self.partner_type == "vendor":
            self._set_first_line_account(self._get_partner_account())

    @api.model
    def create(self, vals):
        if vals.get("name", _("New")) == _("New"):
            vals["name"] = self.env["ir.sequence"].next_by_code(
                "idil.journal.entry"
            ) or _("New")

        # Filter out empty lines
        if "line_ids" in vals:
            vals["line_ids"] = [
                line for line in vals["line_ids"] if line[2].get("account_id")
            ]

        result = super(JournalEntry, self).create(vals)
        result.validate_account_balances()
        result.create_transaction_booking()

        return result

    def write(self, vals):
        result = super(JournalEntry, self).write(vals)
        for entry in self:
            entry.validate_account_balances()
            entry.update_transaction_booking()
        return result

    def unlink(self):
        for entry in self:
            self.env["idil.transaction_booking"].search(
                [("journal_entry_id", "=", entry.id)]
            ).unlink()
        return super(JournalEntry, self).unlink()

    @api.depends("line_ids.debit", "line_ids.credit")
    def _compute_totals(self):
        for entry in self:
            entry.total_debit = sum(line.debit for line in entry.line_ids)
            entry.total_credit = sum(line.credit for line in entry.line_ids)

    @api.constrains("line_ids")
    def _check_debit_credit(self):
        for entry in self:
            if entry.total_debit != entry.total_credit:
                raise ValidationError(
                    _("Total debit (%s) is not equal to total credit (%s).")
                    % (entry.total_debit, entry.total_credit)
                )

    def validate_account_balances(self):
        for entry in self:
            for line in entry.line_ids:
                account = self.env["idil.chart.account"].browse(line.account_id.id)
                account_balance = self.env["idil.transaction_bookingline"].search(
                    [("account_number", "=", account.id)]
                )
                debit_total = sum(line.dr_amount for line in account_balance)
                credit_total = sum(line.cr_amount for line in account_balance)
                current_balance = debit_total - credit_total

                if account.sign == "Dr":
                    if line.credit and current_balance < line.credit:
                        raise ValidationError(
                            _(
                                "Insufficient funds in account ( %s ) for credit amount %s. "
                                "The current account balance is %s."
                            )
                            % (account.name, line.credit, current_balance)
                        )
                elif account.sign == "Cr":
                    if line.debit and current_balance < line.debit:
                        raise ValidationError(
                            _(
                                "Insufficient funds in account ( %s ) for debit amount %s. "
                                "The current account balance is %s."
                            )
                            % (account.name, line.debit, current_balance)
                        )

    def get_manual_transaction_source_id(self):
        trx_source = self.env["idil.transaction.source"].search(
            [("name", "=", "Manual Transaction")], limit=1
        )
        if not trx_source:
            raise ValidationError(
                _('Transaction source "Manual Transaction" not found.')
            )
        return trx_source.id

    # def create_transaction_booking(self):
    #     try:
    #         with self.env.cr.savepoint():
    #             trx_source_id = self.get_manual_transaction_source_id()
    #             for entry in self:
    #                 # Remove existing transaction bookings
    #                 self.env["idil.transaction_booking"].search(
    #                     [("journal_entry_id", "=", entry.id)]
    #                 ).unlink()

    #                 booking_vals = {
    #                     "transaction_number": self.env["ir.sequence"].next_by_code(
    #                         "idil.transaction_booking.sequence"
    #                     )
    #                     or _("New"),
    #                     "reffno": entry.name,
    #                     "trx_date": entry.date,
    #                     "amount": entry.total_debit,  # Assuming total_debit equals the total amount of the transaction
    #                     "debit_total": entry.total_debit,
    #                     "credit_total": entry.total_credit,
    #                     "payment_method": "other",
    #                     "payment_status": "paid",
    #                     "rate": entry.rate,
    #                     "trx_source_id": trx_source_id,
    #                     "journal_entry_id": entry.id,  # Link to the journal entry
    #                 }
    #                 main_booking = self.env["idil.transaction_booking"].create(
    #                     booking_vals
    #                 )
    #                 for line in entry.line_ids:
    #                     if not line.account_id:
    #                         continue  # Skip lines without an account_id
    #                     if line.debit:
    #                         self.env["idil.transaction_bookingline"].create(
    #                             {
    #                                 "transaction_booking_id": main_booking.id,
    #                                 "description": line.description,
    #                                 "account_number": line.account_id.id,
    #                                 "transaction_type": "dr",
    #                                 "dr_amount": line.debit,
    #                                 "cr_amount": 0,
    #                                 "transaction_date": entry.date,
    #                             }
    #                         )
    #                     if line.credit:
    #                         self.env["idil.transaction_bookingline"].create(
    #                             {
    #                                 "transaction_booking_id": main_booking.id,
    #                                 "description": line.description,
    #                                 "account_number": line.account_id.id,
    #                                 "transaction_type": "cr",
    #                                 "cr_amount": line.credit,
    #                                 "dr_amount": 0,
    #                                 "transaction_date": entry.date,
    #                             }
    #                         )
    #     except Exception as e:
    #         logger.error(f"transaction failed: {str(e)}")
    #         raise ValidationError(f"Transaction failed: {str(e)}")

    def create_transaction_booking(self):
        try:
            with self.env.cr.savepoint():
                trx_source_id = self.get_manual_transaction_source_id()
                for entry in self:
                    # Remove existing booking(s) for this journal
                    self.env["idil.transaction_booking"].search(
                        [("journal_entry_id", "=", entry.id)]
                    ).unlink()

                    amount = entry.total_debit

                    # ---- Main booking with partner-specific field ----
                    booking_vals = {
                        "transaction_number": self.env["ir.sequence"].next_by_code(
                            "idil.transaction_booking.sequence"
                        )
                        or _("New"),
                        "reffno": entry.name,
                        "trx_date": entry.date,
                        "amount": amount,
                        "debit_total": entry.total_debit,
                        "credit_total": entry.total_credit,
                        "rate": entry.rate,
                        "trx_source_id": trx_source_id,
                        "journal_entry_id": entry.id,
                    }
                    if entry.partner_type == "customer" and entry.customer_id:
                        booking_vals["customer_id"] = entry.customer_id.id
                        # booking_vals["journal_entry_id"] = entry.id  # already set
                    elif entry.partner_type == "vendor" and entry.vendor_id:
                        booking_vals["vendor_id"] = entry.vendor_id.id

                    main_booking = self.env["idil.transaction_booking"].create(
                        booking_vals
                    )

                    # ---- Booking lines (unchanged) ----
                    for line in entry.line_ids:
                        if not line.account_id:
                            continue
                        if line.debit:
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": main_booking.id,
                                    "description": line.description,
                                    "account_number": line.account_id.id,
                                    "transaction_type": "dr",
                                    "dr_amount": line.debit,
                                    "cr_amount": 0,
                                    "transaction_date": entry.date,
                                }
                            )
                        if line.credit:
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": main_booking.id,
                                    "description": line.description,
                                    "account_number": line.account_id.id,
                                    "transaction_type": "cr",
                                    "cr_amount": line.credit,
                                    "dr_amount": 0,
                                    "transaction_date": entry.date,
                                }
                            )

                    # ---- Partner-specific side records (no payment_method anywhere) ----
                    if entry.partner_type == "vendor" and entry.vendor_id:
                        # Create Vendor Transaction (pending by default)
                        self.env["idil.vendor_transaction"].create(
                            {
                                "order_number": entry.id,  # or entry.name, depending on your model
                                "transaction_number": main_booking.transaction_number,
                                "transaction_date": entry.date,
                                "vendor_id": entry.vendor_id.id,
                                "amount": amount,
                                "remaining_amount": amount,
                                "paid_amount": 0,
                                "reffno": entry.name,
                                "transaction_booking_id": main_booking.id,
                                "payment_status": "pending",
                                # "journal_entry_id": entry.id,  # uncomment if the model has this field
                            }
                        )

                    elif entry.partner_type == "customer" and entry.customer_id:
                        # Create Sales Receipt shell
                        self.env["idil.sales.receipt"].create(
                            {
                                # If your model truly expects "cusotmer_sale_order_id", add it; else omit.
                                # "cusotmer_sale_order_id": entry.id,  # <= ONLY if that exact field exists
                                "customer_id": entry.customer_id.id,
                                "due_amount": amount,
                                "paid_amount": 0,
                                "remaining_amount": amount,
                                # "transaction_booking_id": main_booking.id,  # uncomment if the model has it
                                # "journal_entry_id": entry.id,              # uncomment if the model has it
                                # "reference": entry.name,                   # optional if your model has a field
                            }
                        )
                    # 'others' => no extra record
        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")

    def update_transaction_booking(self):
        try:
            with self.env.cr.savepoint():
                for entry in self:
                    # Remove existing transaction bookings
                    self.env["idil.transaction_booking"].search(
                        [("journal_entry_id", "=", entry.id)]
                    ).unlink()

                    booking_vals = {
                        "transaction_number": self.env["ir.sequence"].next_by_code(
                            "idil.transaction_booking.sequence"
                        )
                        or _("New"),
                        "reffno": entry.name,
                        "trx_date": entry.date,
                        "amount": entry.total_debit,  # Assuming total_debit equals the total amount of the transaction
                        "debit_total": entry.total_debit,
                        "credit_total": entry.total_credit,
                        "journal_entry_id": entry.id,  # Link to the journal entry
                    }
                    main_booking = self.env["idil.transaction_booking"].create(
                        booking_vals
                    )
                    for line in entry.line_ids:
                        if not line.account_id:
                            continue  # Skip lines without an account_id
                        if line.debit:
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": main_booking.id,
                                    "description": line.description,
                                    "account_number": line.account_id.id,
                                    "transaction_type": "dr",
                                    "dr_amount": line.debit,
                                    "cr_amount": 0,
                                    "transaction_date": entry.date,
                                }
                            )
                        if line.credit:
                            self.env["idil.transaction_bookingline"].create(
                                {
                                    "transaction_booking_id": main_booking.id,
                                    "description": line.description,
                                    "account_number": line.account_id.id,
                                    "transaction_type": "cr",
                                    "cr_amount": line.credit,
                                    "dr_amount": 0,
                                    "transaction_date": entry.date,
                                }
                            )
        except Exception as e:
            logger.error(f"transaction failed: {str(e)}")
            raise ValidationError(f"Transaction failed: {str(e)}")


class JournalEntryLine(models.Model):
    _name = "idil.journal.entry.line"
    _description = "Journal Entry Line"
    _order = "id desc"

    entry_id = fields.Many2one(
        "idil.journal.entry", string="Journal Entry", required=True, ondelete="cascade"
    )
    account_id = fields.Many2one("idil.chart.account", string="Account", required=True)
    debit = fields.Monetary(string="Debit", currency_field="currency_id", store=True)
    credit = fields.Monetary(string="Credit", currency_field="currency_id", store=True)
    description = fields.Char(string="Description")
    name = fields.Char(string="Name")
    currency_id = fields.Many2one(
        "res.currency",
        string="Currency",
        related="account_id.currency_id",
        store=True,
        readonly=True,
    )
    # 👇 Will change immediately when account changes; also searchable/groupable (store=True)
    currency_amount_id = fields.Many2one(
        "res.currency",
        string="Currency",
        compute="_compute_currency_amount",
        store=True,
    )

    @api.depends("account_id", "account_id.currency_id", "account_id.company_id")
    def _compute_currency_amount(self):
        """Pick account currency; fallback to the account's company or env company."""
        for rec in self:
            rec.currency_amount_id = rec.account_id.currency_id or (
                rec.account_id.company_id.currency_id
                if rec.account_id and rec.account_id.company_id
                else rec.env.company.currency_id
            )

    @api.onchange("debit")
    def _onchange_debit(self):
        if self.debit:
            self.credit = 0

    @api.onchange("credit")
    def _onchange_credit(self):
        if self.credit:
            self.debit = 0

    @api.onchange("account_id")
    def _onchange_account_id(self):
        if self.account_id and self.currency_id:
            accounts = self.env["idil.chart.account"].search(
                [("currency_id", "=", self.currency_id.id)]
            )
            return {"domain": {"account_id": [("id", "in", accounts.ids)]}}
