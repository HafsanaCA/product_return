/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.return_order = publicWidget.Widget.extend({
    selector: '#hidden_box',
    events: {
        'click #hidden_box_btn': '_onHiddenBoxBtnClick',
        'change #product': '_onProductChange',
    },
    start: function () {
        console.log("Return Order Widget Initialized");
        return this._super.apply(this, arguments);
    },
    _onHiddenBoxBtnClick: function (ev) {
        ev.preventDefault();
        this.$('#hidden_box').modal('show');
    },
    _onProductChange: function (ev) {
        var $product = $(ev.currentTarget);
        var $submitButton = this.$('#submit');
        $submitButton.toggleClass('d-none', $product.val() === 'none');
    },
});