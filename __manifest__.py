{
    'name': 'Website Product Return',
    'version': '1.0',
    'summary': """ Manage Sale Order return from Website """,
    'author': 'Hafsana CA',
    'depends': ['website_sale', 'stock', 'sale_management'],
    'data': [
            'data/ir.sequence.xml',
            'views/res_partner_views.xml',
            'views/sale_order_views.xml',
            'views/sale_return_views.xml',
            'views/stock_picking_views.xml',
            'views/website_thankyou_template.xml',
            'security/ir.model.access.csv',
    ],
    'assets': {
        'web.assets_frontend': [
            'product_return/static/src/js/sale_return.js'
        ]
    },
    'installable': True,
    'auto_install': False,
    'application': False,
}
