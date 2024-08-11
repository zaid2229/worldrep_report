// Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["P and L"] = $.extend(
    {},
    erpnext.financial_statements
);

erpnext.utils.add_dimensions("P and L", 10);

frappe.query_reports["P and L"]["filters"].push({
    fieldname: "accumulated_values",
    label: __("Accumulated Values"),
    fieldtype: "Check",
    default: 1,
});

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
