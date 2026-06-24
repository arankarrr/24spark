'use strict';
'require view';

return view.extend({
	render: function() {
		return E('iframe', {
			src: '/singbox.html',
			title: '24spark',
			style: 'width:100%;min-height:calc(100vh - 110px);border:0;border-radius:8px;background:#0f1117'
		});
	},

	handleSaveApply: null,
	handleSave: null,
	handleReset: null
});
