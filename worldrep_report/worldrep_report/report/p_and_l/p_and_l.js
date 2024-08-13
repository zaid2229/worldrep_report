// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt


// frappe.query_reports["P and L"].onload = function(report) {
//     // Use a small delay to ensure the report is rendered
//     setTimeout(function() {
//         // Select all elements with the specified class
//         var elements = document.querySelectorAll('.dt-cell__content--col-1');

//         // Loop through the elements to find the one with the title "Total Expense (Debit)"
//         elements.forEach(function(element) {
//             if (element.title === "Total Expense (Debit)") {
//                 // Hide the element containing this title
//                 element.style.display = 'none';
//             }
//         });
//     }, 1000);  // Delay for 1 second to allow for report rendering
// };

frappe.require("assets/erpnext/js/financial_statements.js", function () {
	frappe.query_reports["P and L"] = $.extend({}, erpnext.financial_statements);

	erpnext.utils.add_dimensions("P and L", 10);

	frappe.query_reports["P and L"]["filters"].push({
		fieldname: "selected_view",
		label: __("Select View"),
		fieldtype: "Select",
		options: [
			{ value: "Report", label: __("Report View") },
			{ value: "Growth", label: __("Growth View") },
			{ value: "Margin", label: __("Margin View") },
		],
		default: "Report",
		reqd: 1,
	});

	frappe.query_reports["P and L"]["filters"].push({
		fieldname: "include_default_book_entries",
		label: __("Include Default Book Entries"),
		fieldtype: "Check",
		default: 1,
	});
});

frappe.query_reports["P and L"]["filters"].push({
	fieldname: "include_default_book_entries",
	label: __("Include Default FB Entries"),
	fieldtype: "Check",
	default: 1,
});