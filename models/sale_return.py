from odoo import api, fields, models
from odoo.exceptions import UserError


class ReturnOrder(models.Model):
    """Class for sale order return"""
    _name = 'sale.return'
    _inherit = ['portal.mixin', 'mail.thread',
                'mail.activity.mixin']
    _rec_name = "name"
    _order = "name"
    _description = "Return Order"

    @api.model
    def _get_default_name(self):
        """Generates a default name for the return order using an Odoo sequence."""
        return self.env['ir.sequence'].get('sale.return')

    active = fields.Boolean('Active', default=True, help='Is active or not')
    name = fields.Char(string="Name", default=_get_default_name,
                       help='Name of return order')
    product_id = fields.Many2one('product.product', string="Product Variant",
                                 required=False,
                                 help="defines the product variant that need to be returned (less used in multi-line returns)")
    product_tmpl_id = fields.Many2one('product.template',
                                      related="product_id.product_tmpl_id",
                                      store=True,
                                      string="Product", help='Return Product'
                                      )
    return_line_ids = fields.One2many('sale.return.line', 'return_id', string="Return Lines")

    sale_order = fields.Many2one('sale.order', string="Sale Order",
                                 required=True, help='Reference of Sale Order')
    partner_id = fields.Many2one('res.partner', string="Customer",
                                 help='Customer of the return order')
    user_id = fields.Many2one('res.users', string="Responsible",
                              default=lambda self: self.env.user,
                              help='Responsible user for the return order')
    create_date = fields.Datetime(string="Create Date",
                                  help='Create date of the return')
    quantity = fields.Float(string="Quantity", default=0,
                            help='Total return quantity (if needed, computed from lines)')
    received_qty = fields.Float(string="Received Quantity",
                                help='Total received item quantity (if needed, computed from lines)')
    reason = fields.Text("Reason", help='Reason of the return')
    stock_picking = fields.One2many('stock.picking', 'return_order_pick',
                                    domain="[('return_order','=',False)]",
                                    string="Return Picking",
                                    help="Shows the return picking of the corresponding return order")
    picking_count = fields.Integer(compute="_compute_delivery",
                                   string='Picking Order', copy=False,
                                   default=0,
                                   store=True,
                                   help='Picking count of the return')
    delivery_count = fields.Integer(compute="_compute_delivery",
                                    string='Delivery Order', copy=False,
                                    default=0,
                                    store=True,
                                    help='Delivery count of the return')
    state = fields.Selection(
        [('draft', 'Draft'), ('done', 'Done'), ('cancel', 'Canceled')],
        string='Status', readonly=True, default='draft',
        help='Status of return order')
    source_pick = fields.One2many('stock.picking', 'return_order',
                                  string="Source Delivery",
                                  domain="[('return_order_pick','=',False)]",
                                  help="Shows the delivery orders of the corresponding return order")
    note = fields.Text("Note")
    to_refund = fields.Boolean(string='Update SO/PO Quantity',
                               help='Trigger a decrease of the delivered/received quantity in'
                                    ' the associated Sale Order/Purchase Order')

    is_draft = fields.Boolean(compute='_compute_state_booleans', store=True)
    is_not_draft = fields.Boolean(compute='_compute_state_booleans', store=True)
    is_done = fields.Boolean(compute='_compute_state_booleans', store=True)

    @api.depends('state')
    def _compute_state_booleans(self):
        for rec in self:
            rec.is_draft = (rec.state == 'draft')
            rec.is_not_draft = (rec.state != 'draft')
            rec.is_done = (rec.state == 'done')

    def return_confirm(self):
        self.ensure_one()

        if not self.return_line_ids:
            raise UserError("Cannot confirm a return order without any return lines.")

        created_pickings = []
        for line in self.return_line_ids:
            if line.quantity <= 0:
                continue

            stock_picks = self.env['stock.picking'].search(
                [('origin', '=', self.sale_order.name), ('state', '=', 'done')]
            )

            moves = stock_picks.mapped('move_ids_without_package').filtered(
                lambda m: m.product_id == line.product_id and m.state == 'done' and m.product_uom_qty >= line.quantity
            )

            if not moves:
                raise UserError(
                    f"No sufficient delivered quantity found for product '{line.product_id.name}' to return {line.quantity} units. Please verify the quantity or ensure delivery is done.")

            move_to_return = moves[0]
            pick = move_to_return.picking_id

            vals = {
                'picking_id': pick.id,
            }
            return_pick_wizard = self.env['stock.return.picking'].create(vals)

            return_pick_wizard.product_return_moves.unlink()

            return_picking_line_vals = {
                'product_id': line.product_id.id,
                'quantity': line.quantity,
                'wizard_id': return_pick_wizard.id,
                'move_id': move_to_return.id,
                'to_refund': self.to_refund,
            }
            self.env['stock.return.picking.line'].create(return_picking_line_vals)

            new_picking_ids = return_pick_wizard._create_return()
            if new_picking_ids:
                new_picking = new_picking_ids[0]

                customer_location = self.partner_id.property_stock_customer

                new_picking.write({
                    'note': str(self.reason) if self.reason else False,
                    'return_order': False,
                    'return_order_pick': self.id,
                    'return_order_picking': True,
                    'location_id': customer_location.id if customer_location else False,
                })

                created_pickings.append(new_picking.id)
            else:
                raise UserError(f"Failed to create return picking for product '{line.product_id.name}'.")

        if created_pickings:
            self.write({'state': 'done'})
        else:
            raise UserError("No return pickings were created. Please check return lines and original deliveries.")

    def return_cancel(self):
        self.write({'state': 'cancel'})
        if self.stock_picking:
            for rec in self.stock_picking.filtered(
                    lambda s: s.state not in ['done', 'cancel']):
                rec.action_cancel()

    def _get_report_base_filename(self):
        self.ensure_one()
        return 'Sale Return - %s' % (self.name)

    def _compute_access_url(self):
        super(ReturnOrder, self)._compute_access_url()
        for order in self:
            order.access_url = '/my/return_orders/%s' % order.id

    @api.depends('stock_picking', 'state', 'source_pick')
    def _compute_delivery(self):
        for rec in self:
            rec.delivery_count = self.env['stock.picking'].search_count(
                [('return_order', '=', rec.id), ('return_order_picking', '=', False)]) if not rec.source_pick else len(
                rec.source_pick)
            rec.picking_count = self.env['stock.picking'].search_count(
                [('return_order_pick', '=', rec.id),
                 ('return_order_picking', '=', True)]) if not rec.stock_picking else len(rec.stock_picking)

    def action_view_picking(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        pickings = self.stock_picking if self.stock_picking else self.env['stock.picking'].search(
            [('return_order_pick', '=', self.id), ('return_order_picking', '=', True)])
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['res_id'] = pickings.id
        picking_id = pickings.filtered(lambda l: l.picking_type_id.code == 'outgoing')
        if not picking_id:
            picking_id = pickings[0] if pickings else None
        if picking_id:
            action['context'] = dict(self._context,
                                     default_partner_id=self.partner_id.id,
                                     default_picking_type_id=picking_id.picking_type_id.id)
        return action

    def action_view_delivery(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("stock.action_picking_tree_all")
        pickings = self.source_pick if self.source_pick else self.env['stock.picking'].search(
            [('return_order', '=', self.id), ('return_order_picking', '=', False)])
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['res_id'] = pickings.id
        picking_id = pickings.filtered(lambda l: l.picking_type_id.code == 'outgoing')
        if not picking_id:
            picking_id = pickings[0] if pickings else None
        if picking_id:
            action['context'] = dict(self._context,
                                     default_partner_id=self.partner_id.id,
                                     default_picking_type_id=picking_id.picking_type_id.id)
        return action

    @api.onchange('sale_order', 'source_pick')
    def onchange_sale_order(self):
        delivery = None
        product_ids = []
        if self.sale_order:
            self.partner_id = self.sale_order.partner_id
            delivery = self.env['stock.picking'].search(
                [('origin', '=', self.sale_order.name)])
            product_ids = self.sale_order.order_line.mapped('product_id').ids
        if self.source_pick:
            delivery = self.source_pick
            product_ids = delivery.move_ids_without_package.mapped('product_id').ids
        delivery_ids = delivery.ids if delivery else []
        return {'domain': {'source_pick': [('id', 'in', delivery_ids)],
                           'product_id': [('id', 'in', product_ids)]}}

    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id and self.source_pick:
            moves = self.source_pick.mapped(
                'move_ids_without_package').filtered(
                lambda p: p.product_id == self.product_id)
            if moves:
                self.received_qty = sum(moves.mapped('quantity_done'))


class SaleReturnLine(models.Model):
    _name = 'sale.return.line'
    _description = 'Sale Return Line'

    return_id = fields.Many2one(
        'sale.return',
        string="Return Order",
        required=True,
        ondelete='cascade'
    )
    product_id = fields.Many2one(
        'product.product',
        string="Product",
        required=True
    )
    quantity = fields.Float(string="Quantity", required=True)
    reason = fields.Char(string="Reason")
