-- Superset SQL Lab export for Inventory Visibility Agent - GRN feed
-- Use this first because it only depends on dataplatform.mseg.
-- Movement types:
--   101 = Goods receipt
--   105/109 = GR release / accepted GR movement, where used by SAP process

SELECT
    mblnr AS grn_no,
    mjahr AS fiscal_year,
    zeile AS grn_item,
    bwart AS movement_type,
    matnr AS part_no,
    werks AS plant,
    lgort AS storage_location,
    ebeln AS po_no,
    ebelp AS po_item,
    menge AS received_qty,
    meins AS uom,
    charg AS batch_no,
    insmk AS stock_type
FROM dataplatform.mseg
WHERE CAST(bwart AS VARCHAR) IN ('101', '105', '109')
  AND TRY_CAST(mjahr AS INTEGER) >= 2026
ORDER BY mjahr DESC, mblnr DESC, zeile DESC
LIMIT 50000;
