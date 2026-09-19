// RayzorgenDB Native Library
// Compiled to librayzorgen_native.so
// Called from Python via ctypes.

#[no_mangle]
pub extern "C" fn cosine_similarity(
    a_ptr: *const f64, a_len: usize,
    b_ptr: *const f64, b_len: usize,
) -> f64 {
    if a_len != b_len || a_len == 0 {
        return 0.0;
    }
    let a = unsafe { std::slice::from_raw_parts(a_ptr, a_len) };
    let b = unsafe { std::slice::from_raw_parts(b_ptr, b_len) };
    let mut dot = 0.0;
    let mut na = 0.0;
    let mut nb = 0.0;
    for i in 0..a_len {
        dot += a[i] * b[i];
        na += a[i] * a[i];
        nb += b[i] * b[i];
    }
    if na == 0.0 || nb == 0.0 {
        return 0.0;
    }
    let sim = dot / (na.sqrt() * nb.sqrt());
    if sim > 1.0 { 1.0 } else if sim < -1.0 { -1.0 } else { sim }
}

#[no_mangle]
pub extern "C" fn cosine_distance(
    a_ptr: *const f64, a_len: usize,
    b_ptr: *const f64, b_len: usize,
) -> f64 {
    1.0 - cosine_similarity(a_ptr, a_len, b_ptr, b_len)
}

/// Batch cosine. Query vs many vectors.
/// vectors_flat: [v1_0, v1_1, ..., v1_d, v2_0, ...]
/// outputs_ptr: pointer to pre-allocated array of length n_vectors.
#[no_mangle]
pub extern "C" fn cosine_batch(
    query_ptr: *const f64, query_len: usize,
    vectors_ptr: *const f64,
    n_vectors: usize,
    vectors_ptr_len: usize,
    outputs_ptr: *mut f64,
) -> i32 {
    if query_len == 0 || n_vectors == 0 {
        return 1;
    }
    if vectors_ptr_len != n_vectors * query_len {
        return 2;
    }

    let query = unsafe {
        std::slice::from_raw_parts(query_ptr, query_len)
    };
    let vectors = unsafe {
        std::slice::from_raw_parts(vectors_ptr, vectors_ptr_len)
    };
    let outputs = unsafe {
        std::slice::from_raw_parts_mut(outputs_ptr, n_vectors)
    };

    let mut na = 0.0;
    for i in 0..query_len {
        na += query[i] * query[i];
    }
    let na = na.sqrt();
    if na == 0.0 {
        for i in 0..n_vectors {
            outputs[i] = 0.0;
        }
        return 0;
    }

    for v in 0..n_vectors {
        let base = v * query_len;
        let mut dot = 0.0;
        let mut nb = 0.0;
        for i in 0..query_len {
            dot += query[i] * vectors[base + i];
            nb += vectors[base + i] * vectors[base + i];
        }
        if nb == 0.0 {
            outputs[v] = 0.0;
        } else {
            let sim = dot / (na * nb.sqrt());
            outputs[v] = if sim > 1.0 { 1.0 }
                         else if sim < -1.0 { -1.0 }
                         else { sim };
        }
    }
    0
}

#[no_mangle]
pub extern "C" fn euclidean_distance(
    a_ptr: *const f64, a_len: usize,
    b_ptr: *const f64, b_len: usize,
) -> f64 {
    if a_len != b_len {
        return f64::INFINITY;
    }
    let a = unsafe { std::slice::from_raw_parts(a_ptr, a_len) };
    let b = unsafe { std::slice::from_raw_parts(b_ptr, b_len) };
    let mut total = 0.0;
    for i in 0..a_len {
        let d = a[i] - b[i];
        total += d * d;
    }
    total.sqrt()
}

#[no_mangle]
pub extern "C" fn sum_f64(
    values_ptr: *const f64, values_len: usize,
) -> f64 {
    if values_len == 0 {
        return 0.0;
    }
    let values = unsafe {
        std::slice::from_raw_parts(values_ptr, values_len)
    };
    values.iter().sum()
}

#[no_mangle]
pub extern "C" fn version() -> i32 {
    1
}
