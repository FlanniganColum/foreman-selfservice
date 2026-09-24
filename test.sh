#!/usr/bin/env bash

curl -sSk \
  -u 'user:password'  \
  -H 'Accept: application/json' \
  'https://foreman.dmn1.renegadestudios.com/api/job_templates/245/template_inputs?per_page=all' 
  

