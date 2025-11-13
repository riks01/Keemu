# Manual Authentication Testing Checklist

## Test Environment
- **API URL**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **Date**: 2025-10-05

---

## ✅ Test Checklist

### 1. User Registration (POST /api/v1/auth/register)

**Test Data:**
```json
{
  "email": "test@example.com",
  "name": "Test User",
  "password": "testpass123",
  "timezone": "UTC"
}
```

**Expected Response:**
- Status: `201 Created`
- Body contains: `user` object and `access_token`
- Token type: `"bearer"`

**Result:** [ ] PASS  [ ] FAIL

**Notes:**
_______________________________________

---

### 2. User Login (POST /api/v1/auth/login)

**Test Data:**
- username: `test@example.com`
- password: `testpass123`

**Expected Response:**
- Status: `200 OK`
- Body contains: `access_token` and `token_type: "bearer"`

**Result:** [ ] PASS  [ ] FAIL

**Notes:**
_______________________________________

---

### 3. Get Current User (GET /api/v1/auth/me)

**Prerequisites:**
- Authorize with token from login

**Expected Response:**
- Status: `200 OK`
- Body contains user details:
  - `id`, `email`, `name`, `timezone`, `is_active`

**Result:** [ ] PASS  [ ] FAIL

**Notes:**
_______________________________________

---

### 4. Login with Wrong Password (Negative Test)

**Test Data:**
- username: `test@example.com`
- password: `wrongpassword`

**Expected Response:**
- Status: `401 Unauthorized`
- Detail: `"Incorrect email or password"`

**Result:** [ ] PASS  [ ] FAIL

**Notes:**
_______________________________________

---

### 5. Access Protected Endpoint Without Token (Negative Test)

**Test:** Access `/api/v1/auth/me` without Authorization header

**Expected Response:**
- Status: `401 Unauthorized`
- Detail: `"Not authenticated"`

**Result:** [ ] PASS  [ ] FAIL

**Notes:**
_______________________________________

---

### 6. Duplicate Registration (Negative Test)

**Test:** Register with same email again

**Test Data:**
```json
{
  "email": "test@example.com",
  "name": "Another User",
  "password": "differentpass",
  "timezone": "UTC"
}
```

**Expected Response:**
- Status: `400 Bad Request`
- Detail: `"Email already registered"`

**Result:** [ ] PASS  [ ] FAIL

**Notes:**
_______________________________________

---

## Summary

**Total Tests:** 6  
**Passed:** ___  
**Failed:** ___  

**Overall Status:** [ ] ALL PASS  [ ] SOME FAILURES

**Tested By:** _______________________  
**Date:** _______________________

---

## Notes

Add any additional observations or issues here:

_______________________________________
_______________________________________
_______________________________________