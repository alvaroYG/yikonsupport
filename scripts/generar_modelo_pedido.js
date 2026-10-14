// Modelo de pedido de compra (Purchase Order) para clientes de Yikon Genomics. Bilingüe ES/EN, A4.
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, AlignmentType,
  WidthType, BorderStyle, ShadingType, VerticalAlign, Footer, TableLayoutType,
} = require("docx");

const MAGENTA = "A61C92", GRIS = "5C5C5C", GRIS_CLARO = "F4F1F4", RELLENO = "FBFAFB", BORDE = "D9CFD8";
const FUENTE = "Calibri";
const ANCHO = 10466; // A4 (11906) menos márgenes de 720 a cada lado

const t = (text, o = {}) => new TextRun({ text, font: FUENTE, size: o.size || 18, bold: o.bold, italics: o.italics, color: o.color || "222222" });
const p = (runs, o = {}) => new Paragraph({ children: Array.isArray(runs) ? runs : [runs], alignment: o.align, spacing: { before: o.before || 0, after: o.after || 0 } });
// Etiqueta bilingüe: "Español / English" (el inglés, más suave)
const etiqueta = (es, en, o = {}) => p([t(es, { bold: true, size: o.size || 16, color: o.color || GRIS }), t(" / " + en, { size: o.size || 16, color: o.color || "8A8A8A", italics: true })]);

const sinBordes = { top: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
                    left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" }, right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" } };
const bordeFino = { style: BorderStyle.SINGLE, size: 4, color: BORDE };
const bordes = { top: bordeFino, bottom: bordeFino, left: bordeFino, right: bordeFino };

function celda(children, ancho, o = {}) {
  return new TableCell({
    children: Array.isArray(children) ? children : [children],
    width: { size: ancho, type: WidthType.DXA },
    borders: o.borders || bordes,
    shading: o.fondo ? { type: ShadingType.CLEAR, color: "auto", fill: o.fondo } : undefined,
    margins: { top: o.mt ?? 45, bottom: o.mb ?? 45, left: o.ml ?? 100, right: o.mr ?? 100 },
    verticalAlign: o.valign || VerticalAlign.TOP,
    columnSpan: o.span,
  });
}
function tabla(filas, anchos, o = {}) {
  return new Table({ rows: filas, columnWidths: anchos, width: { size: anchos.reduce((a, b) => a + b, 0), type: WidthType.DXA },
                     layout: TableLayoutType.FIXED, borders: o.borders });
}
// Campo para rellenar: etiqueta encima y un hueco con fondo suave
function campo(es, en, ancho, o = {}) {
  const hueco = (o.valor ? [p(t(o.valor, { size: 18, bold: o.negrita }))] : [p(t(" ", { size: 18 }))]);
  for (let i = 1; i < (o.lineas || 1); i++) hueco.push(p(t(" ", { size: 18 })));
  return celda([etiqueta(es, en), ...hueco], ancho, { fondo: o.valor ? GRIS_CLARO : RELLENO, span: o.span });
}
// Título de bloque: barra magenta
function tituloBloque(es, en, ancho, span) {
  return celda(p([t(es.toUpperCase(), { bold: true, size: 17, color: "FFFFFF" }), t("  /  " + en.toUpperCase(), { size: 15, color: "F3D6EE" })]),
               ancho, { fondo: MAGENTA, span, borders: sinBordes, mt: 50, mb: 50, valign: VerticalAlign.CENTER });
}
const espacio = (n = 120) => new Paragraph({ children: [], spacing: { before: 0, after: n } });

const logo = fs.readFileSync(require("path").join(__dirname, "..", "app", "static", "img", "yikon-logo.png"));

// ---------- Cabecera: logo + título ----------
const cabecera = tabla([new TableRow({ children: [
  celda(new Paragraph({ children: [new ImageRun({ type: "png", data: logo, transformation: { width: 150, height: 65 } })] }), 4200, { borders: sinBordes, valign: VerticalAlign.CENTER }),
  celda([
    p(t("PEDIDO DE COMPRA", { bold: true, size: 36, color: MAGENTA }), { align: AlignmentType.RIGHT }),
    p(t("PURCHASE ORDER", { size: 24, color: GRIS }), { align: AlignmentType.RIGHT }),
    p(t("Adjúntelo a su pedido en la plataforma de Yikon Genomics", { size: 15, color: "8A8A8A", italics: true }), { align: AlignmentType.RIGHT, before: 60 }),
    p(t("Please attach it to your order on the Yikon Genomics platform", { size: 15, color: "8A8A8A", italics: true }), { align: AlignmentType.RIGHT }),
  ], ANCHO - 4200, { borders: sinBordes, valign: VerticalAlign.CENTER }),
] })], [4200, ANCHO - 4200], { borders: sinBordes });

// ---------- Datos del pedido ----------
const q = ANCHO / 4;
const datosPedido = tabla([new TableRow({ children: [
  campo("Nº de pedido", "PO number", q),
  campo("Fecha", "Date", q),
  campo("Nº de proforma Yikon", "Yikon proforma no.", q),
  campo("Entrega deseada", "Requested delivery", q),
] })], [q, q, q, q]);

// ---------- Cliente / Proveedor ----------
const mitad = (ANCHO - 200) / 2;
const hueco = 200;
function bloqueCliente() {
  return tabla([
    new TableRow({ children: [tituloBloque("Cliente", "Customer", mitad, 2)] }),
    new TableRow({ children: [campo("Empresa / centro", "Company / clinic", mitad, { span: 2 })] }),
    new TableRow({ children: [campo("CIF / NIF", "VAT no.", mitad / 2), campo("Teléfono", "Phone", mitad / 2)] }),
    new TableRow({ children: [campo("Persona de contacto", "Contact person", mitad, { span: 2 })] }),
    new TableRow({ children: [campo("Email", "Email", mitad, { span: 2 })] }),
  ], [mitad / 2, mitad / 2]);
}
function bloqueProveedor() {
  return tabla([
    new TableRow({ children: [tituloBloque("Proveedor", "Supplier", mitad, 2)] }),
    new TableRow({ children: [campo("Empresa", "Company", mitad, { span: 2, valor: "Yikon Genomics, S.L.", negrita: true })] }),
    new TableRow({ children: [campo("CIF", "VAT no.", mitad / 2, { valor: "B44777787" }), campo("País", "Country", mitad / 2, { valor: "España / Spain" })] }),
    new TableRow({ children: [campo("Dirección", "Address", mitad, { span: 2, valor: "Ronda General Mitre, 49, 1º 1ª · 08017 Barcelona" })] }),
    new TableRow({ children: [campo("Persona de contacto en Yikon", "Yikon contact", mitad, { span: 2 })] }),
  ], [mitad / 2, mitad / 2]);
}
const partes = tabla([new TableRow({ children: [
  celda(bloqueCliente(), mitad, { borders: sinBordes, mt: 0, mb: 0, ml: 0, mr: 0 }),
  celda(p(t("")), hueco, { borders: sinBordes }),
  celda(bloqueProveedor(), mitad, { borders: sinBordes, mt: 0, mb: 0, ml: 0, mr: 0 }),
] })], [mitad, hueco, mitad], { borders: sinBordes });

// ---------- Material solicitado ----------
const col = [1900, 4466, 1100, 1450, 1550]; // suma = ANCHO
const cab = (es, en, ancho, align) => celda([p(t(es, { bold: true, size: 16, color: "FFFFFF" }), { align }), p(t(en, { size: 14, color: "F3D6EE", italics: true }), { align })],
                                             ancho, { fondo: MAGENTA, borders: { ...bordes, top: { style: BorderStyle.SINGLE, size: 4, color: MAGENTA } } });
const filasLinea = [];
for (let i = 0; i < 7; i++) {
  filasLinea.push(new TableRow({ height: { value: 340, rule: "atLeast" }, cantSplit: true, children: col.map((a) => celda(p(t(" ")), a, { fondo: i % 2 ? RELLENO : "FFFFFF" })) }));
}
const totalFila = (es, en, destacado) => new TableRow({ children: [
  celda(p(t("")), col[0] + col[1] + col[2], { span: 3, borders: sinBordes }),
  celda(p([t(es, { bold: true, size: 16, color: destacado ? MAGENTA : GRIS }), t(" / " + en, { size: 14, color: "8A8A8A", italics: true })], { align: AlignmentType.RIGHT }), col[3], { fondo: destacado ? "F7E8F5" : GRIS_CLARO }),
  celda(p(t(" ", { bold: destacado })), col[4], { fondo: destacado ? "F7E8F5" : RELLENO }),
] });
const lineas = tabla([
  new TableRow({ tableHeader: true, children: [
    cab("Referencia", "Code", col[0]), cab("Descripción", "Description", col[1]),
    cab("Cantidad", "Quantity", col[2], AlignmentType.CENTER), cab("Precio ud. €", "Unit price €", col[3], AlignmentType.RIGHT),
    cab("Importe €", "Amount €", col[4], AlignmentType.RIGHT),
  ] }),
  ...filasLinea,
  totalFila("Subtotal", "Subtotal"),
  totalFila("Portes", "Shipping"),
  totalFila("IVA", "VAT"),
  totalFila("TOTAL", "TOTAL", true),
], col);

// ---------- Entrega / Facturación ----------
function bloqueEntrega() {
  return tabla([
    new TableRow({ children: [tituloBloque("Dirección de entrega", "Delivery address", mitad, 2)] }),
    new TableRow({ children: [campo("A la atención de", "Attention", mitad, { span: 2 })] }),
    new TableRow({ children: [campo("Dirección (calle, CP, ciudad, país)", "Address (street, ZIP, city, country)", mitad, { span: 2, lineas: 2 })] }),
    new TableRow({ children: [campo("Teléfono", "Phone", mitad / 2), campo("Horario de recepción", "Receiving hours", mitad / 2)] }),
  ], [mitad / 2, mitad / 2]);
}
function bloqueFactura() {
  return tabla([
    new TableRow({ children: [tituloBloque("Datos de facturación", "Invoicing details", mitad, 2)] }),
    new TableRow({ children: [campo("Razón social", "Legal name", mitad, { span: 2 })] }),
    new TableRow({ children: [campo("Dirección fiscal", "Billing address", mitad, { span: 2, lineas: 2 })] }),
    new TableRow({ children: [campo("CIF / NIF", "VAT no.", mitad / 2), campo("Email para facturas", "Invoice email", mitad / 2)] }),
  ], [mitad / 2, mitad / 2]);
}
const entregaFactura = tabla([new TableRow({ children: [
  celda(bloqueEntrega(), mitad, { borders: sinBordes, mt: 0, mb: 0, ml: 0, mr: 0 }),
  celda(p(t("")), hueco, { borders: sinBordes }),
  celda(bloqueFactura(), mitad, { borders: sinBordes, mt: 0, mb: 0, ml: 0, mr: 0 }),
] })], [mitad, hueco, mitad], { borders: sinBordes });

// ---------- Condiciones, observaciones y firma ----------
const casilla = (es, en) => [t("☐ ", { size: 18, color: MAGENTA }), t(es, { size: 16 }), t(" / " + en + "     ", { size: 15, color: "8A8A8A", italics: true })];
const c3 = [3600, 3600, ANCHO - 7200];
const condiciones = tabla([
  new TableRow({ cantSplit: true, children: [tituloBloque("Condiciones y observaciones", "Terms and notes", ANCHO, 3)] }),
  new TableRow({ children: [
    celda([etiqueta("Forma de pago", "Payment terms"),
           p([...casilla("Transferencia 30 días", "Bank transfer 30 days")], { before: 40 }),
           p([...casilla("Transferencia 60 días", "Bank transfer 60 days")]),
           p([...casilla("Otra:", "Other:"), t("________________", { size: 16, color: "BBBBBB" })])], c3[0], { fondo: RELLENO }),
    celda([etiqueta("Observaciones", "Notes"),
           p(t("P. ej.: caducidad lo más larga posible", { size: 14, italics: true, color: "9A9A9A" }), { before: 40 }),
           p(t("E.g.: longest possible expiry date", { size: 14, italics: true, color: "9A9A9A" })),
           p(t(" "))], c3[1], { fondo: RELLENO }),
    celda([etiqueta("Firma y sello", "Signature and stamp"), p(t(" ")), p(t(" ")),
           p([t("Nombre / Name: ", { size: 15, color: GRIS })], { before: 60 }),
           p([t("Cargo / Position: ", { size: 15, color: GRIS })])], c3[2], { fondo: RELLENO }),
  ] }),
], c3);

// ---------- Pie ----------
const pie = new Footer({ children: [
  new Paragraph({ border: { top: { style: BorderStyle.SINGLE, size: 6, color: MAGENTA, space: 4 } }, alignment: AlignmentType.CENTER, children: [
    t("Indique el nº de pedido en las facturas y albaranes · ", { size: 14, color: GRIS }),
    t("Please quote the PO number on invoices and delivery notes", { size: 14, color: "8A8A8A", italics: true }),
  ] }),
  p(t("Yikon Genomics, S.L. · CIF B44777787 · Barcelona (España)", { size: 14, color: "8A8A8A" }), { align: AlignmentType.CENTER }),
] });

const doc = new Document({
  creator: "Yikon Genomics", title: "Pedido de compra / Purchase order", description: "Modelo de pedido de compra para clientes de Yikon Genomics",
  styles: { default: { document: { run: { font: FUENTE, size: 18 } } } },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 560, bottom: 700, left: 720, right: 720, footer: 360 } } },
    footers: { default: pie },
    children: [cabecera, espacio(100), datosPedido, espacio(100), partes, espacio(100), lineas, espacio(100), entregaFactura, espacio(100), condiciones],
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(process.argv[2] || require("path").join(__dirname, "..", "app", "recursos", "Pedido_de_compra_Yikon.docx"), buf); console.log("ok"); });
