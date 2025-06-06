import base64
import logging
from collections import OrderedDict
from datetime import datetime
from urllib.parse import quote
from odoo.exceptions import AccessError, MissingError, UserError # Added UserError
from odoo import http
from odoo.http import request
from odoo.tools import image_process
from odoo.tools.translate import _
from odoo.addons.portal.controllers.portal import CustomerPortal
from werkzeug.exceptions import BadRequest

_logger = logging.getLogger(__name__)

class ReturnCustomerPortal(CustomerPortal):
    """Class for add portal for customer return"""

    def _prepare_home_portal_values(self, counters):
        """To add portal return count"""
        values = super()._prepare_home_portal_values(counters)
        if 'return_count' in counters:
            # Filter returns for the current user's partner_id
            values['return_count'] = request.env['sale.return'].sudo().search_count([
                ('state', 'in', ['draft', 'confirm', 'done', 'cancel']),
                ('partner_id', '=', request.env.user.partner_id.id) # Filter by current portal user's partner
            ])
        return values

    @http.route(['/my/return_orders', '/my/return_orders/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_sale_return(self, page=1, date_begin=None, date_end=None, sortby=None, filterby=None, **kw):
        """Function for customer portal order return"""
        values = self._prepare_portal_layout_values()
        sale_return = request.env['sale.return'].sudo() # Use sudo for portal access
        domain = [('partner_id', '=', request.env.user.partner_id.id)] # Filter by current portal user's partner

        searchbar_sortings = {
            'date': {'label': _('Newest'), 'order': 'create_date desc'},
            'name': {'label': _('Name'), 'order': 'name'},
            'sale': {'label': _('Sale Order'), 'order': 'sale_order'},
        }

        # default sort by value
        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        if date_begin and date_end:
            domain += [('create_date', '>', date_begin), ('create_date', '<=', date_end)]

        searchbar_filters = {
            'all': {'label': _('All'), 'domain': [('state', 'in', ['draft', 'confirm', 'done', 'cancel'])]},
            'confirm': {'label': _('Confirmed'), 'domain': [('state', '=', 'confirm')]},
            'cancel': {'label': _('Cancelled'), 'domain': [('state', '=', 'cancel')]},
            'done': {'label': _('Done'), 'domain': [('state', '=', 'done')]},
        }
        # default filter by value
        if not filterby:
            filterby = 'all'
        domain += searchbar_filters[filterby]['domain']
        return_count = sale_return.search_count(domain)
        # pager
        pager = request.website.pager(
            url="/my/return_orders",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=return_count,
            page=page,
            step=self._items_per_page
        )
        # content according to pager and archive selected
        orders = sale_return.search(domain, order=order, limit=self._items_per_page, offset=pager['offset'])
        request.session['my_return_history'] = orders.ids[:100]
        values.update({
            'date': date_begin,
            'orders': orders, # Already sudo'd above
            'page_name': 'Sale_Return',
            'default_url': '/my/return_orders',
            'pager': pager,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items())),
            'searchbar_sortings': searchbar_sortings,
            'sortby': sortby,
            'filterby': filterby, # Ensure filterby is passed to template for active filter
        })
        return request.render("product_return.portal_my_returns", values)

    @http.route(['/my/return_orders/<int:order_id>'], type='http', auth="public", website=True)
    def portal_my_return_detail(self, order_id=None, access_token=None, report_type=None, download=False, **kw):
        """Function for my order details"""
        try:
            # Ensure proper access check for portal records
            order_sudo = self._document_check_access('sale.return', order_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')
        if report_type in ('html', 'pdf', 'text'):
            return self._show_report(model=order_sudo, report_type=report_type,
                                     report_ref='product_return.report_sale_returns',
                                     download=download)

        values = self._sale_return_get_page_view_values(order_sudo, access_token, **kw)
        return request.render("product_return.portal_sale_return_page", values)

    def _sale_return_get_page_view_values(self, order, access_token, **kwargs):
        """Function for sale return get page view values"""
        def resize_to_48(b64source):
            if not b64source:
                b64source = request.env['ir.binary']._placeholder()
            else:
                b64source = base64.b64decode(b64source)
            return base64.b64encode(image_process(b64source, size=(48, 48)))
        values = {
            'orders': order,
            'resize_to_48': resize_to_48,
        }
        return self._get_page_view_values(order, access_token, values, 'my_return_history', False, **kwargs)

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
            if not reason or reason.strip() == '': # Ensure reason is not empty or just whitespace
                return request.redirect(
                    f'/sale_return_form/{order_id}?error=no_reason&message=Please%20provide%20a%20reason%20for%20the%20return')

            return_lines = []
            valid_products_selected = False
            for key in kwargs:
                if key.startswith('product_'):
                    try:
                        product_id = int(kwargs[key])
                        qty_key = f'qty_{product_id}'
                        qty_str = kwargs.get(qty_key, '').strip() # Get quantity string and strip whitespace

                        # If quantity string is empty, treat as 0
                        if not qty_str:
                            qty = 0.0
                        else:
                            qty = float(qty_str)

                        if qty <= 0:
                            continue # Skip products with 0 or negative return quantity

                        # Find the specific order line to validate against delivered quantity
                        order_line = order.order_line.filtered(
                            lambda l: l.product_id.id == product_id
                        )

                        if order_line and order_line.qty_delivered >= qty:
                            return_lines.append((0, 0, {
                                'product_id': product_id,
                                'quantity': qty,
                                # Optionally add reason per line if needed in the future, otherwise, global reason
                                'reason': reason # Use the main reason for each line for consistency
                            }))
                            valid_products_selected = True
                        elif order_line:
                            _logger.warning(f"Attempted to return {qty} of {order_line.product_id.name} but only {order_line.qty_delivered} delivered or quantity too high.")
                            # Optionally, you could add an error redirect here if a user tries to return more than delivered
                            # raise UserError(f"Cannot return more than delivered for product {order_line.product_id.name}")
                        else:
                            _logger.warning(f"Product ID {product_id} from form not found in sale order lines.")

                    except ValueError: # Handles cases where qty_str is not a valid number
                        _logger.error(f"Invalid quantity value received for product key {key}: {kwargs.get(f'qty_{int(kwargs[key])}')}")
                        continue
                    except Exception as e:
                        _logger.error(f"Error processing product {key}: {e}", exc_info=True)
                        continue

            if not valid_products_selected: # Check if at least one valid product was selected with a positive quantity
                return request.redirect(
                    f'/sale_return_form/{order_id}?error=no_valid_products&message=Please%20select%20at%20least%20one%20product%20with%20a%20positive%20return%20quantity')

            # Create the main return order
            ret_order = request.env['sale.return'].sudo().create({
                'partner_id': order.partner_id.id,
                'sale_order': order.id,
                'reason': reason, # Main reason for the entire return
                'user_id': request.env.uid,
                'create_date': datetime.now(),
                'state': 'draft',
                'return_line_ids': return_lines, # Pass the list of return lines
            })

            # The logic below for setting source_pick on stock pickings is not ideal here.
            # This logic should rather be triggered during the 'return_confirm'
            # method in the 'sale.return' model, after pickings are created by the wizard.
            # Removing this block from here.

            # Example of what was here, and should be moved/handled differently:
            # stock_picks = request.env['stock.picking'].search([('origin', '=', order.name)])
            # for line in ret_order.return_line_ids:
            #     moves = stock_picks.mapped('move_ids_without_package').filtered(
            #         lambda p: p.product_id.id == line.product_id.id
            #     )
            #     if moves:
            #         moves = moves.sorted('product_uom_qty', reverse=True)
            #         moves[0].picking_id.return_order = ret_order.id
            #         moves[0].picking_id.return_order_picking = False


            return request.redirect('/my/request-thank-you')

        except UserError as e: # Catch Odoo's UserError for specific messages
            message = quote(str(e).replace('\n', ' ').replace('\r', ' '))
            return request.redirect(f'/sale_return_form/{kwargs.get("order_id", 0)}?error=client_error&message={message}')
        except BadRequest as e:
            if 'invalid CSRF token' in str(e).lower():
                return request.redirect(
                    f'/sale_return_form/{kwargs.get("order_id", 0)}?error=csrf_error&message=Invalid%20or%20missing%20CSRF%20token')
            message = quote(str(e).replace('\n', ' ').replace('\r', ' '))
            return request.redirect(
                f'/sale_return_form/{kwargs.get("order_id", 0)}?error=server_error&message={message}')
        except Exception as e:
            _logger.exception("Error during sale return submission from portal") # Log the full traceback
            message = quote(str(e).replace('\n', ' ').replace('\r', ' '))
            return request.redirect(
                f'/sale_return_form/{kwargs.get("order_id", 0)}?error=server_error&message={message}')
