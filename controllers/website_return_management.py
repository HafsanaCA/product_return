# -*- coding: utf-8 -*-
from datetime import datetime
from odoo import http
from odoo.http import request
from odoo.addons.website.controllers import main

class CustomerRegistration(main.Home):

    @http.route('/sale_return', type='http', methods=['POST'], auth="user", website=True)
    def sale_return(self, **kwargs):
        """Controller to create return orders for multiple products"""
        try:
            order_id = int(kwargs.get('order_id', 0))
            order = request.env['sale.order'].sudo().browse(order_id)

            if not order or order.partner_id != request.env.user.partner_id:
                return request.redirect('/my')

            reason = kwargs.get('reason')
            if not reason:
                return request.redirect('/my/orders/%s' % order_id)

            created = False
            for key, value in kwargs.items():
                if key.startswith('product_'):
                    product_id = int(value)
                    qty_key = f'qty_{product_id}'
                    qty_val = float(kwargs.get(qty_key, 0))

                    if qty_val <= 0:
                        continue

                    product = request.env['product.product'].sudo().browse(product_id)
                    order_line = order.order_line.filtered(lambda l: l.product_id.id == product_id and l.qty_delivered >= qty_val)
                    if not order_line:
                        continue

                    ret_order = request.env['sale.return'].sudo().create({
                        'partner_id': order.partner_id.id,
                        'sale_order': order.id,
                        'product_id': product_id,
                        'quantity': qty_val,
                        'reason': reason,
                        'user_id': request.env.uid,
                        'create_date': datetime.now(),
                        'state': 'draft',
                    })
                    created = True

                    stock_picks = request.env['stock.picking'].search([('origin', '=', order.name)])
                    moves = stock_picks.mapped('move_ids_without_package').filtered(lambda p: p.product_id.id == product_id)
                    if moves:
                        moves = moves.sorted('product_uom_qty', reverse=True)
                        moves[0].picking_id.return_order = ret_order.id
                        moves[0].picking_id.return_order_picking = False

            if not created:
                return request.redirect('/my/orders/%s' % order_id)

            return request.redirect('/my/request-thank-you')

        except Exception:
            return request.redirect('/my/orders/%s' % kwargs.get('order_id', 0))

    @http.route('/my/request-thank-you', type='http', auth='user', website=True)
    def maintenance_request_thanks(self):
        return request.render('product_return.customers_request_thank_page')
