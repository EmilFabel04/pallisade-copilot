-- AlterEnum
-- This migration adds more than one value to an enum.
-- With PostgreSQL versions 11 and earlier, this is not possible
-- in a single migration. This can be worked around by creating
-- multiple migrations, each migration adding only one value to
-- the enum.


ALTER TYPE "MonitorKind" ADD VALUE 'NULL_CHECK';
ALTER TYPE "MonitorKind" ADD VALUE 'UNIQUENESS_CHECK';
ALTER TYPE "MonitorKind" ADD VALUE 'RANGE_VALIDATION';
ALTER TYPE "MonitorKind" ADD VALUE 'ACCEPTED_VALUES';
ALTER TYPE "MonitorKind" ADD VALUE 'DATE_CONSISTENCY';
ALTER TYPE "MonitorKind" ADD VALUE 'DATA_TYPE_VALIDATION';
ALTER TYPE "MonitorKind" ADD VALUE 'OUTLIER_DETECTION';
