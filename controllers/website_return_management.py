# -*- coding: utf-8 -*-
import logging
from datetime import datetime
from urllib.parse import quote
from odoo import http
from odoo.http import request
from odoo.addons.website.controllers import main
from werkzeug.exceptions import BadRequest

_logger = logging.getLogger(__name__)

class CustomerRegistration(main.Home):

    @http.route('/sale_return_form/<int:order_id>', type='http', auth="user", website=True, csrf=True)
    def show_sale_return_form(self, order_id):
        if not request.session.uid:
            return request.redirect('/web/login?redirect=/sale_return_form/%s' % order_id)

        order = request.env['sale.order'].sudo().browse(order_id)
        if not order.exists() or order.partner_id != request.env.user.partner_id:
            return request.redirect('/my')

        response = request.render('product_return.sale_return_form_template', {
            'sale_order': order,
            'error': request.params.get('error'),
            'message': request.params.get('message'),
        })
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    @http.route('/sale_return', type='http', methods=['POST'], auth="user", website=True, csrf=True)
    def sale_return(self, **kwargs):
        try:
            if not request.session.uid:
                return request.redirect('/web/login?redirect=/sale_return_form/%s' % kwargs.get('order_id', 0))

            order_id = int(kwargs.get('order_id', 0))
            order = request.env['sale.order'].sudo().browse(order_id)
            if not order or order.partner_id != request.env.user.partner_id:
                return request.redirect('/my')

            reason = kwargs.get('reason')
            if not reason:
                return request.redirect(
                    f'/sale_return_form/{order_id}?error=no_reason&message=Please%20provide%20a%20reason%20for%20the%20return')

            return_lines = []
            for key in kwargs:
                if key.startswith('product_'):
                    try:
                        product_id = int(kwargs[key])
                        qty_key = f'qty_{product_id}'
                        qty_str = kwargs.get(qty_key)
                        if not qty_str:
                            continue

                        qty = float(qty_str)
                        if qty <= 0:
                            continue

                        order_line = order.order_line.filtered(
                            lambda l: l.product_id.id == product_id and l.qty_delivered >= qty
                        )
                        if order_line:
                            return_lines.append((0, 0, {
                                'product_id': product_id,
                                'quantity': qty,
                            }))
                    except Exception:
                        continue  # Skip any invalid product or quantity data

            if not return_lines:
                return request.redirect(
                    f'/sale_return_form/{order_id}?error=no_valid_products&message=Please%20select%20at%20least%20one%20valid%20product')

            ret_order = request.env['sale.return'].sudo().create({
                'partner_id': order.partner_id.id,
                'sale_order': order.id,
                'reason': reason,
                'user_id': request.env.uid,
                'create_date': datetime.now(),
                'state': 'draft',
                'return_line_ids': return_lines,
            })

            stock_picks = request.env['stock.picking'].search([('origin', '=', order.name)])
            for line in ret_order.return_line_ids:
                moves = stock_picks.mapped('move_ids_without_package').filtered(
                    lambda p: p.product_id.id == line.product_id.id
                )
                if moves:
                    moves = moves.sorted('product_uom_qty', reverse=True)
                    moves[0].picking_id.return_order = ret_order.id
                    moves[0].picking_id.return_order_picking = False

            return request.redirect('/my/request-thank-you')

        except BadRequest as e:
            if 'invalid CSRF token' in str(e).lower():
                return request.redirect(
                    f'/sale_return_form/{kwargs.get("order_id", 0)}?error=csrf_error&message=Invalid%20or%20missing%20CSRF%20token')
            message = quote(str(e).replace('\n', ' ').replace('\r', ' '))
            return request.redirect(
                f'/sale_return_form/{kwargs.get("order_id", 0)}?error=server_error&message={message}')
        except Exception as e:
            message = quote(str(e).replace('\n', ' ').replace('\r', ' '))
            return request.redirect(
                f'/sale_return_form/{kwargs.get("order_id", 0)}?error=server_error&message={message}')

    @http.route('/my/request-thank-you', type='http', auth="user", website=True)
    def maintenance_request_thanks(self):
        response = request.render('product_return.customers_request_thank_page')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

