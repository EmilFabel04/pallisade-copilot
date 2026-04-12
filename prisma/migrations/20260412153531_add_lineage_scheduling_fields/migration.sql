-- Add lineage scheduling fields to PipelineStack
ALTER TABLE "PipelineStack" ADD COLUMN "lastLineageExtractedAt" TIMESTAMP(3),
ADD COLUMN "lineageExtractionEnabled" BOOLEAN NOT NULL DEFAULT false;
