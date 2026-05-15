# Face Search Engine - Comprehensive Testing Prompt

## 🎯 Testing Objectives

This testing suite is designed to rigorously validate the face search engine implementation with focus on:
- **Race conditions** and concurrent operation safety
- **Resource usage** optimization (CPU, memory, disk I/O)
- **Read-only operations** (never delete files or database records)
- **Folder access privileges** (admin vs non-admin scenarios)
- **Media file validation** (skip small files, thumbnails, assets)

---

## 📋 Test Suite Index

| Suite | Category | Priority | Estimated Time |
|-------|----------|----------|----------------|
| 1 | File Discovery & Scanning | High | 30 min |
| 2 | Media File Validation | High | 20 min |
| 3 | Face Detection & Processing | High | 45 min |
| 4 | Embedding Generation & Indexing | High | 40 min |
| 5 | OneDrive Integration | Medium | 35 min |
| 6 | Database Operations | High | 40 min |
| 7 | API & Search Functionality | High | 45 min |
| 8 | Clustering & Person Management | Medium | 30 min |
| 9 | Dashboard & Monitoring | Medium | 25 min |
| 10 | Error Handling & Recovery | High | 35 min |
| 11 | Race Conditions & Concurrency | Critical | 50 min |
| 12 | Access Privileges & Security | High | 30 min |

---

## 🔧 Pre-Test Setup Requirements

### Environment Preparation
- [ ] Ensure test directory exists: `D:\FaceSearch\TestData`
- [ ] Create subdirectories: `/valid_faces`, `/invalid_files`, `/small_files`, `/thumbnails`, `/protected`
- [ ] Prepare test images: 
  - Valid face images (various sizes: 100KB, 500KB, 2MB, 5MB)
  - Non-face images
  - Corrupted image files
  - Files < 10KB (should be skipped)
  - Thumbnail files (< 50KB)
- [ ] Backup existing database before tests
- [ ] Document current system resource baseline (CPU, RAM, disk usage)

### Configuration Verification
- [ ] Verify `config.json` settings:
  ```json
  {
    "min_file_size": 10240,
    "supported_formats": ["jpg", "jpeg", "png", "bmp", "webp"],
    "face_detection_threshold": 0.7,
    "batch_size": 32,
    "max_concurrent_workers": 4
  }
  ```
- [ ] Confirm logging is enabled at DEBUG level
- [ ] Verify monitoring tools are ready (task manager, resource monitor, etc.)

---

## 📝 Test Cases

### Suite 1: File Discovery & Scanning

#### 1.1 Directory Scanning Efficiency
- [ ] **TC-1.1.1**: Scan directory with 1000 mixed files, measure time taken
  - Expected: Complete within 30 seconds
  - Monitor: CPU usage < 60%, Memory increase < 200MB
  
- [ ] **TC-1.1.2**: Scan nested directory structure (5 levels deep)
  - Expected: All valid media files discovered
  - Verify: No files missed, no duplicates in manifest

- [ ] **TC-1.1.3**: Scan directory while files are being added (concurrent)
  - Expected: New files detected in next scan cycle
  - Verify: No race conditions, no crashes

#### 1.2 Manifest Management
- [ ] **TC-1.2.1**: Create manifest for 500 files
  - Expected: Manifest saved successfully
  - Verify: File count matches, paths are absolute

- [ ] **TC-1.2.2**: Load existing manifest after application restart
  - Expected: Manifest loaded without re-scanning
  - Verify: Timestamp check, incremental updates work

- [ ] **TC-1.2.3**: Handle manifest corruption gracefully
  - Action: Corrupt manifest file manually
  - Expected: System regenerates manifest, logs warning

#### 1.3 File Exclusion Rules
- [ ] **TC-1.3.1**: Verify files < 10KB are skipped
  - Setup: Create 20 files under 10KB
  - Expected: All skipped, logged as "File too small"
  
- [ ] **TC-1.3.2**: Verify thumbnail files are excluded
  - Setup: Files with "thumb" or "thumbnail" in name
  - Expected: Excluded from processing, logged appropriately

- [ ] **TC-1.3.3**: Verify asset/cache folders are skipped
  - Setup: Create `__pycache__`, `.git`, `node_modules` folders
  - Expected: Entire folders skipped during scan

---

### Suite 2: Media File Validation

#### 2.1 Size Filtering
- [ ] **TC-2.1.1**: Process files exactly at minimum size threshold (10KB)
  - Expected: Files processed normally
  
- [ ] **TC-2.1.2**: Attempt to process files below threshold (5KB)
  - Expected: Skipped with appropriate log message
  - Verify: No embedding generated, no DB entry

- [ ] **TC-2.1.3**: Process large files (10MB+)
  - Expected: Successfully processed
  - Monitor: Memory usage doesn't spike excessively

#### 2.2 Magic Bytes Validation
- [ ] **TC-2.2.1**: Validate genuine JPEG files
  - Expected: Pass validation, processed normally

- [ ] **TC-2.2.2**: Detect fake JPEG (renamed PNG with .jpg extension)
  - Expected: Rejected, logged as "Invalid file format"
  
- [ ] **TC-2.2.3**: Handle truncated/corrupted headers
  - Setup: Files with incomplete magic bytes
  - Expected: Graceful rejection, no crash

#### 2.3 Format Support Matrix
- [ ] **TC-2.3.1**: Test all supported formats (JPG, PNG, BMP, WEBP)
  - Expected: All formats processed successfully
  
- [ ] **TC-2.3.2**: Attempt unsupported formats (GIF, TIFF, RAW)
  - Expected: Skipped with "Unsupported format" log
  
- [ ] **TC-2.3.3**: Test case-insensitive extension handling (.JPG vs .jpg)
  - Expected: Both handled correctly

---

### Suite 3: Face Detection & Processing

#### 3.1 Detection Thresholds
- [ ] **TC-3.1.1**: Detect faces with confidence > 0.9
  - Expected: High accuracy detection
  
- [ ] **TC-3.1.2**: Test boundary cases (confidence 0.65-0.75)
  - Expected: Configurable threshold respected
  
- [ ] **TC-3.1.3**: Reject low-confidence detections (< 0.5)
  - Expected: No face recorded, logged as low confidence

#### 3.2 Multi-Face Images
- [ ] **TC-3.2.1**: Process image with 2 faces
  - Expected: Both faces detected, separate embeddings
  
- [ ] **TC-3.2.2**: Process image with 10+ faces
  - Expected: All faces detected, performance acceptable
  
- [ ] **TC-3.2.3**: Handle overlapping face bounding boxes
  - Expected: Proper separation or merging logic applied

#### 3.3 Edge Cases
- [ ] **TC-3.3.1**: Process image with no faces
  - Expected: Logged as "No faces detected", no DB entry
  
- [ ] **TC-3.3.2**: Process partially obscured faces
  - Expected: Detection based on visibility threshold
  
- [ ] **TC-3.3.3**: Handle extreme angles/profiles
  - Expected: Consistent with model capabilities

#### 3.4 Face Cropping & Normalization
- [ ] **TC-3.4.1**: Verify face crop includes proper padding
  - Expected: 20% padding around face bounding box
  
- [ ] **TC-3.4.2**: Test crop boundary handling (face near image edge)
  - Expected: Crop adjusted to stay within image bounds
  
- [ ] **TC-3.4.3**: Verify normalized face size (224x224)
  - Expected: Consistent embedding input size

---

### Suite 4: Embedding Generation & Indexing

#### 4.1 Batched Processing
- [ ] **TC-4.1.1**: Generate embeddings for batch of 32 faces
  - Expected: Completed in single batch, efficient GPU/CPU usage
  
- [ ] **TC-4.1.2**: Handle batch size not divisible by 32
  - Setup: 50 faces (32 + 18)
  - Expected: Two batches processed correctly
  
- [ ] **TC-4.1.3**: Monitor memory during large batch (100 faces)
  - Expected: No memory leaks, stable usage

#### 4.2 FAISS Index Operations
- [ ] **TC-4.2.1**: Add single embedding to index
  - Expected: Index size increases by 1
  
- [ ] **TC-4.2.2**: Add batch of 100 embeddings
  - Expected: Atomic operation, all or nothing
  
- [ ] **TC-4.2.3**: Save and reload index after 1000 additions
  - Expected: All embeddings preserved, searchable

#### 4.3 Deduplication
- [ ] **TC-4.3.1**: Add same face image twice
  - Expected: Second addition skipped or flagged as duplicate
  
- [ ] **TC-4.3.2**: Add near-duplicate faces (same person, different photo)
  - Expected: Both stored, clustering identifies similarity
  
- [ ] **TC-4.3.3**: Verify hash-based deduplication
  - Expected: Identical files detected by hash

---

### Suite 5: OneDrive Integration

#### 5.1 Multi-Detection Workflow
- [ ] **TC-5.1.1**: Track file with multiple detection attempts
  - Setup: Trigger detection 3 times on same file
  - Expected: Status tracked, redundant processing avoided
  
- [ ] **TC-5.1.2**: Verify detection status persistence after restart
  - Expected: Status recovered from database

#### 5.2 Download & Revert
- [ ] **TC-5.2.1**: Download file from OneDrive for processing
  - Expected: Temporary copy created, original untouched
  
- [ ] **TC-5.2.2**: Verify revert after processing
  - Expected: Temp file deleted, OneDrive unchanged
  
- [ ] **TC-5.2.3**: Handle download failure gracefully
  - Setup: Simulate network error
  - Expected: Retry logic or graceful failure

#### 5.3 Status Tracking
- [ ] **TC-5.3.1**: Update file status through workflow stages
  - Stages: Pending → Downloading → Processing → Indexed
  
- [ ] **TC-5.3.2**: Query files by status
  - Expected: Accurate counts per status
  
- [ ] **TC-5.3.3**: Handle stale statuses (process crashed mid-way)
  - Expected: Recovery mechanism resets stuck statuses

---

### Suite 6: Database Operations

#### 6.1 Concurrent Writes
- [ ] **TC-6.1.1**: Simulate 10 threads writing simultaneously
  - Expected: No deadlocks, all writes succeed
  
- [ ] **TC-6.1.2**: Write during read operations
  - Expected: Readers don't block writers unnecessarily
  
- [ ] **TC-6.1.3**: Stress test with 1000 rapid inserts
  - Expected: Database remains consistent, no corruption

#### 6.2 Query Performance
- [ ] **TC-6.2.1**: Measure query time for 10,000 records
  - Expected: < 100ms for indexed queries
  
- [ ] **TC-6.2.2**: Test complex joins (faces ↔ files ↔ persons)
  - Expected: Efficient execution plan
  
- [ ] **TC-6.2.3**: Verify index usage on frequently queried columns
  - Expected: Query planner uses indexes

#### 6.3 Data Integrity
- [ ] **TC-6.3.1**: Verify foreign key constraints
  - Action: Attempt to delete file with associated faces
  - Expected: Cascade delete or constraint violation
  
- [ ] **TC-6.3.2**: Test transaction rollback on error
  - Setup: Force error mid-transaction
  - Expected: All changes rolled back
  
- [ ] **TC-6.3.3**: Verify ACID properties under load
  - Expected: Consistency maintained

---

### Suite 7: API & Search Functionality

#### 7.1 Search Accuracy
- [ ] **TC-7.1.1**: Search for exact match face
  - Expected: Top result is the same person
  
- [ ] **TC-7.1.2**: Search with different photo of same person
  - Expected: Same person in top 5 results
  
- [ ] **TC-7.1.3**: Search with face of unknown person
  - Expected: Low similarity scores, no false positives

#### 7.2 Multi-Face Search
- [ ] **TC-7.2.1**: Upload image with 3 faces for search
  - Expected: All 3 faces searched independently
  
- [ ] **TC-7.2.2**: Return results grouped by detected face
  - Expected: Clear mapping: Face 1 → Results, Face 2 → Results

#### 7.3 Performance Benchmarks
- [ ] **TC-7.3.1**: Measure search latency for 10K embeddings
  - Expected: < 500ms for top 10 results
  
- [ ] **TC-7.3.2**: Test concurrent search requests (10 users)
  - Expected: All complete within 2 seconds
  
- [ ] **TC-7.3.3**: Monitor resource usage during peak load
  - Expected: CPU < 80%, Memory stable

#### 7.4 Authentication & Authorization
- [ ] **TC-7.4.1**: Test API with valid JWT token
  - Expected: Request succeeds
  
- [ ] **TC-7.4.2**: Test API with expired token
  - Expected: 401 Unauthorized
  
- [ ] **TC-7.4.3**: Test API without token
  - Expected: 401 Unauthorized

---

### Suite 8: Clustering & Person Management

#### 8.1 Quality-Aware Clustering
- [ ] **TC-8.1.1**: Cluster 100 faces of 10 people
  - Expected: ~10 clusters formed
  
- [ ] **TC-8.1.2**: Verify cluster quality scores
  - Expected: High intra-cluster similarity
  
- [ ] **TC-8.1.3**: Handle outliers (faces that don't fit any cluster)
  - Expected: Outliers flagged for manual review

#### 8.2 Verification Workflow
- [ ] **TC-8.2.1**: Present cluster for user verification
  - Expected: UI shows representative faces
  
- [ ] **TC-8.2.2**: Accept/Reject cluster
  - Expected: Accepted → Person created, Rejected → Split or flag
  
- [ ] **TC-8.2.3**: Merge two verified clusters
  - Expected: Single person with combined faces

#### 8.3 Incremental Clustering
- [ ] **TC-8.3.1**: Add new faces to existing clusters
  - Expected: Correct assignment or new cluster creation
  
- [ ] **TC-8.3.2**: Re-cluster after significant additions (100+ new faces)
  - Expected: Improved cluster quality

---

### Suite 9: Dashboard & Monitoring

#### 9.1 Real-Time Updates
- [ ] **TC-9.1.1**: Monitor processing queue in real-time
  - Expected: Queue length updates without refresh
  
- [ ] **TC-9.1.2**: WebSocket connection stability test (1 hour)
  - Expected: No disconnections, heartbeats working
  
- [ ] **TC-9.1.3**: Handle client reconnection
  - Expected: State synchronized on reconnect

#### 9.2 Statistics Accuracy
- [ ] **TC-9.2.1**: Verify total files count matches database
  - Expected: Exact match
  
- [ ] **TC-9.2.2**: Verify processing speed calculation
  - Expected: Accurate faces/minute metric
  
- [ ] **TC-9.2.3**: Test statistics after application restart
  - Expected: Persistent stats recovered correctly

#### 9.3 Alert System
- [ ] **TC-9.3.1**: Trigger high CPU alert (> 90% for 5 min)
  - Expected: Alert logged/displayed
  
- [ ] **TC-9.3.2**: Trigger disk space warning (< 10% free)
  - Expected: Warning issued
  
- [ ] **TC-9.3.3**: Test alert throttling (prevent spam)
  - Expected: Max 1 alert per 5 minutes per type

---

### Suite 10: Error Handling & Recovery

#### 10.1 Permission Errors
- [ ] **TC-10.1.1**: Attempt to read file without permissions
  - Expected: Graceful skip, error logged
  
- [ ] **TC-10.1.2**: Attempt to write to protected directory
  - Expected: Fail gracefully, no crash
  
- [ ] **TC-10.1.3**: Continue processing after permission error
  - Expected: Other files processed normally

#### 10.2 File Corruption
- [ ] **TC-10.2.1**: Process corrupted image file
  - Expected: Detected, skipped, logged
  
- [ ] **TC-10.2.2**: Handle truncated embedding file
  - Expected: Regenerate or skip
  
- [ ] **TC-10.2.3**: Recover from database corruption
  - Setup: Corrupt SQLite file slightly
  - Expected: Backup restored or rebuild initiated

#### 10.3 Resource Limits
- [ ] **TC-10.3.1**: Test behavior when disk is full
  - Expected: Graceful degradation, no data loss
  
- [ ] **TC-10.3.2**: Handle out-of-memory scenario
  - Expected: Process terminated safely, cleanup performed
  
- [ ] **TC-10.3.3**: Test recovery after resource exhaustion
  - Expected: System resumes normal operation after resources freed

---

### ⚠️ Suite 11: Race Conditions & Concurrency (CRITICAL)

#### 11.1 File System Race Conditions
- [ ] **TC-11.1.1**: Two processes scan same directory simultaneously
  - Expected: No duplicate entries, no missed files
  
- [ ] **TC-11.1.2**: File deleted during processing
  - Setup: Start processing, delete file mid-operation
  - Expected: Handled gracefully, no crash
  
- [ ] **TC-11.1.3**: File modified during read
  - Setup: Start reading, modify file content
  - Expected: Use original content or retry

#### 11.2 Database Race Conditions
- [ ] **TC-11.2.1**: Concurrent inserts with same face hash
  - Expected: Only one inserted, others rejected/deduplicated
  
- [ ] **TC-11.2.2**: Read-modify-write on same record
  - Setup: Two threads increment counter simultaneously
  - Expected: Correct final value (no lost updates)
  
- [ ] **TC-11.2.3**: Lock contention under heavy load
  - Expected: No deadlocks, reasonable wait times

#### 11.3 Index Race Conditions
- [ ] **TC-11.3.1**: Search during index update
  - Expected: Consistent results (old or new, not mixed)
  
- [ ] **TC-11.3.2**: Multiple threads adding to FAISS index
  - Expected: Thread-safe, no corruption
  
- [ ] **TC-11.3.3**: Index save during active writes
  - Expected: Atomic save or queue writes

#### 11.4 Cache Coherency
- [ ] **TC-11.4.1**: Update database, verify cache invalidation
  - Expected: Cache updated or invalidated
  
- [ ] **TC-11.4.2**: Stale cache detection
  - Setup: Modify data directly in DB, bypass cache
  - Expected: Cache detects staleness on next read

---

### 🔐 Suite 12: Access Privileges & Security

#### 12.1 Admin vs Non-Admin Execution
- [ ] **TC-12.1.1**: Run full pipeline as admin
  - Expected: All folders accessible
  
- [ ] **TC-12.1.2**: Run full pipeline as standard user
  - Expected: Protected folders skipped gracefully
  
- [ ] **TC-12.1.3**: Compare results between admin/non-admin
  - Expected: Difference only in protected folder access

#### 12.2 Protected Folder Handling
- [ ] **TC-12.2.1**: Scan Windows protected folders (Program Files)
  - Expected: Access denied logged, no crash
  
- [ ] **TC-12.2.2**: Scan user-protected folders (explicit deny)
  - Expected: Permission error handled
  
- [ ] **TC-12.2.3**: Verify no elevation prompts during normal operation
  - Expected: Runs without UAC prompts

#### 12.3 Audit Logging
- [ ] **TC-12.3.1**: Verify all access attempts logged
  - Expected: Success and failure logged
  
- [ ] **TC-12.3.2**: Log includes user context (admin/standard)
  - Expected: User SID or name in logs
  
- [ ] **TC-12.3.3**: Sensitive operations audited (DB writes, deletes)
  - Expected: Detailed audit trail

---

## 📊 Resource Monitoring Checklist

During ALL tests, monitor and record:

### CPU Usage
- [ ] Baseline idle: _____%
- [ ] Peak during scanning: _____%
- [ ] Peak during face detection: _____%
- [ ] Peak during indexing: _____%
- [ ] Average sustained load: _____%

### Memory Usage
- [ ] Baseline: _____ MB
- [ ] Peak usage: _____ MB
- [ ] Memory leaks detected: Yes / No
- [ ] GC frequency: _____ times/hour

### Disk I/O
- [ ] Read throughput: _____ MB/s
- [ ] Write throughput: _____ MB/s
- [ ] IOPS during peak: _____
- [ ] Disk queue length: _____

### Network (if applicable)
- [ ] OneDrive download speed: _____ Mbps
- [ ] API response times: _____ ms avg
- [ ] WebSocket latency: _____ ms

---

## 🚨 Critical Failure Conditions

Tests should be marked as **FAILED** if any of the following occur:

- ❌ Application crash or unhandled exception
- ❌ Data corruption (database or index)
- ❌ Memory leak > 500MB over 1 hour
- ❌ Deadlock lasting > 30 seconds
- ❌ Race condition causing data inconsistency
- ❌ Security vulnerability exposed
- ❌ Resource exhaustion without graceful degradation

---

## 📈 Post-Test Analysis

After completing all test suites:

1. **Compile Results**
   - Total tests run: _____
   - Passed: _____
   - Failed: _____
   - Skipped: _____

2. **Performance Summary**
   - Fastest operation: _________________
   - Slowest operation: _________________
   - Bottleneck identified: _________________

3. **Resource Efficiency Rating**
   - CPU efficiency: Excellent / Good / Fair / Poor
   - Memory efficiency: Excellent / Good / Fair / Poor
   - Disk I/O efficiency: Excellent / Good / Fair / Poor

4. **Critical Issues Found**
   ```
   List any critical issues discovered:
   1. 
   2. 
   3. 
   ```

5. **Recommendations**
   ```
   Priority improvements:
   1. 
   2. 
   3. 
   ```

---

## ✅ Test Completion Criteria

All tests are considered complete when:

- [ ] All 12 test suites executed
- [ ] All critical test cases (Priority: High/Critical) passed
- [ ] No critical failure conditions triggered
- [ ] Resource usage within acceptable limits
- [ ] Race condition tests show no data inconsistencies
- [ ] Privilege tests confirm secure behavior
- [ ] Documentation updated with findings
- [ ] Performance benchmarks recorded for regression testing

---

**Note:** This is a READ-ONLY test suite. Under no circumstances should tests delete files, database records, or index data. All tests must preserve existing data integrity.

**Version:** 1.0  
**Last Updated:** $(Get-Date -Format "yyyy-MM-dd")  
**Author:** Face Search Engine Test Team
