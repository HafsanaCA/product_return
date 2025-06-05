{
    'name': 'Website Product Return',
    'version': '1.0',
    'summary': """ Manage Sale Order return from Website """,
    'author': 'Hafsana CA',
    'depends': ['website_sale', 'stock', 'sale_management','product'],
    'data': [
            'security/ir.model.access.csv',
            'data/ir_sequence.xml',
            'views/website_thankyou_template.xml',
            'views/sale_return_views.xml',
            'views/sale_order_views.xml',
            'views/res_partner_views.xml',
            'views/stock_picking_views.xml',
            'views/form_template_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            # 'product_return/static/src/js/sale_return.js'
        ]
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
