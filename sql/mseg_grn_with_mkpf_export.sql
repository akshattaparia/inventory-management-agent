-- Richer GRN export if dataplatform.mkpf is available.
-- MKPF adds posting / entry date-time fields that help the app show live GRN recency.

WITH mkpf_one AS (
    SELECT
        mblnr,
        mjahr,
        MAX(CAST(budat AS VARCHAR)) AS grn_date,
        MAX(CAST(cpudt AS VARCHAR)) AS sap_entry_date,
        MAX(CAST(cputm AS VARCHAR)) AS sap_entry_time,
        MAX(CAST(usnam AS VARCHAR)) AS created_by
    FROM dataplatform.mkpf
    GROUP BY mblnr, mjahr
)
SELECT
    mseg.mblnr AS grn_no,
    mseg.mjahr AS fiscal_year,
    mseg.zeile AS grn_item,
    mseg.bwart AS movement_type,
    mseg.matnr AS part_no,
    mseg.werks AS plant,
    mseg.lgort AS storage_location,
    mseg.ebeln AS po_no,
    mseg.ebelp AS po_item,
    mseg.menge AS received_qty,
    mseg.meins AS uom,
    mseg.charg AS batch_no,
    mseg.insmk AS stock_type,
    mkpf_one.grn_date,
    mkpf_one.sap_entry_date,
    mkpf_one.sap_entry_time,
    mkpf_one.created_by
FROM dataplatform.mseg AS mseg
LEFT JOIN mkpf_one
  ON mseg.mblnr = mkpf_one.mblnr
 AND mseg.mjahr = mkpf_one.mjahr
WHERE CAST(mseg.bwart AS VARCHAR) IN ('101', '105', '109')
  AND TRY_CAST(mseg.mjahr AS INTEGER) >= 2026
ORDER BY mseg.mjahr DESC, mseg.mblnr DESC, mseg.zeile DESC
LIMIT 50000;
